#!/usr/bin/env python3
"""人事(HR)関連の最新研究・公的調査データを収集し、Markdownレポートを生成する。

収集元(査読論文DB・公的機関に限定):
  - OpenAlex   : 海外の査読付き学術論文
  - J-STAGE    : 国内の学術論文
  - RSSフィード : 厚生労働省・JILPT・RIETI・NBER などの公的機関/研究機関

使い方:
  python scripts/collect_hr_research.py [--config config/sources.yml] [--out reports/]

出力:
  - reports/YYYY-MM-DD.md : 週次レポート
  - data/seen.json        : 既出アイテムの記録(週をまたぐ重複を排除)
"""

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
import yaml
from email.utils import parsedate_tz

USER_AGENT = "hr-research-collector/1.0 (GitHub Actions weekly digest)"
TIMEOUT = 30
SEEN_RETENTION_DAYS = 180


# ----------------------------------------------------------------------
# ユーティリティ
# ----------------------------------------------------------------------

def http_get(url, params=None):
    resp = requests.get(url, params=params, timeout=TIMEOUT,
                        headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return resp


def strip_ns(tag):
    """XMLタグから名前空間を除去する。"""
    return tag.split("}", 1)[-1] if "}" in tag else tag


def truncate(text, limit=300):
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ----------------------------------------------------------------------
# 収集: OpenAlex(海外論文)
# ----------------------------------------------------------------------

def reconstruct_abstract(inverted_index):
    """OpenAlexのabstract_inverted_indexから抄録テキストを復元する。"""
    if not inverted_index:
        return ""
    positions = []
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort()
    return " ".join(word for _, word in positions)


def collect_openalex(cfg, since):
    items, errors = [], []
    oa = cfg.get("openalex") or {}
    for query in oa.get("queries", []):
        try:
            resp = http_get(
                "https://api.openalex.org/works",
                params={
                    "filter": (
                        f"title_and_abstract.search:{query},"
                        f"from_publication_date:{since.isoformat()},"
                        "type:article"
                    ),
                    "sort": "publication_date:desc",
                    "per-page": oa.get("max_per_query", 15),
                    "select": "id,title,publication_date,primary_location,"
                              "doi,abstract_inverted_index,authorships",
                },
            )
            for work in resp.json().get("results", []):
                loc = work.get("primary_location") or {}
                src = (loc.get("source") or {}).get("display_name") or ""
                authors = [a.get("author", {}).get("display_name", "")
                           for a in (work.get("authorships") or [])[:3]]
                items.append({
                    "id": work.get("doi") or work.get("id"),
                    "title": work.get("title") or "(no title)",
                    "url": work.get("doi") or work.get("id"),
                    "date": work.get("publication_date") or "",
                    "venue": src,
                    "authors": ", ".join(a for a in authors if a),
                    "summary": truncate(
                        reconstruct_abstract(work.get("abstract_inverted_index"))),
                })
        except Exception as exc:  # noqa: BLE001 - 1クエリの失敗で全体を止めない
            errors.append(f"OpenAlex ({query}): {exc}")
    return items, errors


# ----------------------------------------------------------------------
# 収集: J-STAGE(国内論文)
# ----------------------------------------------------------------------

def jstage_field_text(elem):
    """J-STAGEのフィールドは <ja>/<en> の入れ子になることがある。日本語優先で取り出す。"""
    for sub in elem:
        if strip_ns(sub.tag) == "ja":
            text = "".join(sub.itertext()).strip()
            if text:
                return text
    return "".join(elem.itertext()).strip()


def collect_jstage(cfg, since):
    """J-STAGE論文検索API(service=3)。

    APIは発行「年」までしか絞り込めないため今年の論文を取得し、
    週次の新着判定は seen.json による重複排除に任せる。
    """
    items, errors = [], []
    js = cfg.get("jstage") or {}
    for query in js.get("queries", []):
        try:
            resp = http_get(
                "https://api.jstage.jst.go.jp/searchapi/do",
                params={
                    "service": 3,
                    "article": query,
                    "pubyearfrom": since.year,
                    "count": js.get("max_per_query", 10),
                    "sortflg": 2,  # 発行日の新しい順
                },
            )
            root = ET.fromstring(resp.content)
            for entry in root.iter():
                if strip_ns(entry.tag) != "entry":
                    continue
                fields = {}
                link = ""
                for child in entry:
                    tag = strip_ns(child.tag)
                    if tag == "link":
                        link = link or child.get("href") \
                            or (child.text or "").strip()
                    elif tag == "article_link":
                        link = link or jstage_field_text(child)
                    elif tag == "author":
                        names = [
                            "".join(n.itertext()).strip()
                            for n in child.iter()
                            if strip_ns(n.tag) == "name"
                        ]
                        names = [n for n in names if n]
                        fields["author"] = (", ".join(names[:3])
                                            if names else jstage_field_text(child))
                    else:
                        text = jstage_field_text(child)
                        if text:
                            fields.setdefault(tag, text)
                title = fields.get("article_title") or fields.get("title") or ""
                if not title:
                    continue
                items.append({
                    "id": link or f"jstage:{title}",
                    "title": title,
                    "url": link,
                    "date": fields.get("pubyear", ""),
                    "venue": fields.get("material_title")
                             or fields.get("journal_title") or "J-STAGE",
                    "authors": fields.get("author", ""),
                    "summary": "",
                    "query": query,
                })
        except Exception as exc:  # noqa: BLE001
            errors.append(f"J-STAGE ({query}): {exc}")
    return items, errors


# ----------------------------------------------------------------------
# 収集: RSSフィード(公的機関)
# RSS 1.0(RDF)/ RSS 2.0 / Atom を標準ライブラリだけで解析する
# ----------------------------------------------------------------------

def parse_feed_date(text):
    """RFC822形式(RSS 2.0)とISO形式(RDF/Atom)の両方に対応した日付解析。"""
    text = (text or "").strip()
    if not text:
        return None
    parsed = parsedate_tz(text)
    if parsed:
        return date(*parsed[:3])
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        return date(*(int(g) for g in match.groups()))
    return None


def parse_feed_entries(content):
    """フィードXMLから (title, link, published) のリストを返す。"""
    root = ET.fromstring(content)
    entries = []
    for elem in root.iter():
        if strip_ns(elem.tag) not in ("item", "entry"):
            continue
        title, link, published = "", "", None
        for child in elem:
            tag = strip_ns(child.tag)
            text = (child.text or "").strip()
            if tag == "title" and text:
                title = text
            elif tag == "link":
                link = link or child.get("href") or text
            elif tag in ("pubDate", "date", "updated", "published", "issued"):
                published = published or parse_feed_date(text)
        entries.append((title, link, published))
    return entries


def collect_feeds(cfg, since):
    grouped, errors = {}, []
    for feed_cfg in cfg.get("feeds", []):
        name = feed_cfg.get("name", feed_cfg.get("url", "feed"))
        keywords = [str(k).lower() for k in (feed_cfg.get("keywords") or [])]
        try:
            resp = http_get(feed_cfg["url"])
            found = []
            for title, link, published in parse_feed_entries(resp.content):
                if not title:
                    continue
                if keywords and not any(k in title.lower() for k in keywords):
                    continue
                # 日付が取れて期間外なら除外。日付が無い場合は seen.json に任せる
                if published and published < since:
                    continue
                found.append({
                    "id": link or f"{name}:{title}",
                    "title": title,
                    "url": link,
                    "date": published.isoformat() if published else "",
                    "venue": name,
                    "authors": "",
                    "summary": "",
                })
            grouped[name] = found
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {exc}")
            grouped[name] = None  # 取得失敗の印
    return grouped, errors


# ----------------------------------------------------------------------
# 重複排除(seen.json)
# ----------------------------------------------------------------------

def load_seen(path):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def filter_new(items, seen, today):
    fresh = []
    for item in items:
        key = item["id"]
        if key in seen:
            continue
        seen[key] = today.isoformat()
        fresh.append(item)
    return fresh


def prune_seen(seen, today):
    cutoff = (today - timedelta(days=SEEN_RETENTION_DAYS)).isoformat()
    return {k: v for k, v in seen.items() if v >= cutoff}


# ----------------------------------------------------------------------
# レポート生成
# ----------------------------------------------------------------------

def render_item(item):
    lines = [f"### {item['title']}"]
    meta = []
    if item.get("venue"):
        meta.append(f"掲載: {item['venue']}")
    if item.get("date"):
        meta.append(f"発行: {item['date']}")
    if item.get("authors"):
        meta.append(f"著者: {item['authors']}")
    if meta:
        lines.append("- " + " / ".join(meta))
    if item.get("url"):
        lines.append(f"- <{item['url']}>")
    if item.get("summary"):
        lines.append(f"- 概要: {item['summary']}")
    return "\n".join(lines)


def render_report(today, since, openalex_items, jstage_items, feed_groups, errors):
    total = (len(openalex_items) + len(jstage_items)
             + sum(len(v) for v in feed_groups.values() if v))
    lines = [
        f"# 人事研究ウィークリーレポート {today.isoformat()}",
        "",
        f"収集期間: {since.isoformat()} 〜 {today.isoformat()} / "
        f"新着 **{total} 件**",
        "",
        "収集元は査読論文データベース(OpenAlex・J-STAGE)および"
        "公的機関・研究機関に限定しています。",
        "",
    ]

    lines.append(f"## 🌍 海外の学術論文({len(openalex_items)}件)")
    lines.append("")
    if openalex_items:
        for item in openalex_items:
            lines.append(render_item(item))
            lines.append("")
    else:
        lines.append("今週の新着はありませんでした。")
        lines.append("")

    lines.append(f"## 🇯🇵 国内の学術論文 - J-STAGE({len(jstage_items)}件)")
    lines.append("")
    if jstage_items:
        for item in jstage_items:
            lines.append(render_item(item))
            lines.append("")
    else:
        lines.append("今週の新着はありませんでした。")
        lines.append("")

    lines.append("## 🏛 公的機関・研究機関の新着")
    lines.append("")
    for name, group in feed_groups.items():
        if group is None:
            lines.append(f"### {name}")
            lines.append("⚠️ 取得に失敗しました(config/sources.yml のURLを確認してください)。")
            lines.append("")
            continue
        lines.append(f"### {name}({len(group)}件)")
        if group:
            for item in group:
                link = f" — <{item['url']}>" if item["url"] else ""
                d = f"({item['date']}) " if item["date"] else ""
                lines.append(f"- {d}{item['title']}{link}")
        else:
            lines.append("- 今週の新着はありませんでした。")
        lines.append("")

    if errors:
        lines.append("## ⚠️ 収集エラー")
        lines.append("")
        for err in errors:
            lines.append(f"- {err}")
        lines.append("")

    return "\n".join(lines)


# ----------------------------------------------------------------------
# メイン
# ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/sources.yml")
    parser.add_argument("--out", default="reports")
    parser.add_argument("--data", default="data")
    args = parser.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    today = date.today()
    since = today - timedelta(days=int(cfg.get("window_days", 8)))

    seen_path = Path(args.data) / "seen.json"
    seen = load_seen(seen_path)

    all_errors = []

    openalex_items, errs = collect_openalex(cfg, since)
    all_errors += errs
    jstage_items, errs = collect_jstage(cfg, since)
    all_errors += errs
    feed_groups, errs = collect_feeds(cfg, since)
    all_errors += errs

    openalex_items = filter_new(openalex_items, seen, today)
    jstage_items = filter_new(jstage_items, seen, today)
    feed_groups = {
        name: (filter_new(group, seen, today) if group is not None else None)
        for name, group in feed_groups.items()
    }

    report = render_report(today, since, openalex_items, jstage_items,
                           feed_groups, all_errors)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"{today.isoformat()}.md"
    report_path.write_text(report, encoding="utf-8")

    seen_path.parent.mkdir(parents=True, exist_ok=True)
    seen_path.write_text(
        json.dumps(prune_seen(seen, today), ensure_ascii=False, indent=1),
        encoding="utf-8",
    )

    total = (len(openalex_items) + len(jstage_items)
             + sum(len(v) for v in feed_groups.values() if v))
    print(f"report={report_path}")
    print(f"new_items={total}")

    # GitHub Actions から参照できるよう出力変数を書き出す
    import os
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a", encoding="utf-8") as fh:
            fh.write(f"report_path={report_path}\n")
            fh.write(f"new_items={total}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
