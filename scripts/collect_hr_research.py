#!/usr/bin/env python3
"""人事(HR)関連の最新研究・記事を収集し、Markdownレポートを生成する。

流れ:
  1. 新聞・業界誌の新着記事からトレンドキーワードを集計(本日のトレンド)
  2. 国内外の論文(OpenAlex・J-STAGE)をトレンドとの関連度でスコアリングし
     上位数件(既定3件)だけを「注目論文」として掲載
  3. 各記事に日本語のAI要約を付与

収集元(論文DB・業界誌・新聞・公的機関に限定):
  - OpenAlex   : 海外の査読付き学術論文
  - J-STAGE    : 国内の学術論文
  - RSSフィード : 新聞報道(Google News検索・NHK)、業界誌(HR NOTE・HRzine)、
                 公的機関(厚生労働省・RIETI・NBER)

使い方:
  python scripts/collect_hr_research.py [--config config/sources.yml] [--out reports/]

出力:
  - reports/YYYY-MM-DD.md : デイリーレポート
  - data/seen.json        : 既出アイテムの記録(日をまたぐ重複を排除)
"""

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
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
    seen_titles = set()  # 同一論文が複数ソースに索引されるためタイトルでも排除
    oa = cfg.get("openalex") or {}
    for query in oa.get("queries", []):
        try:
            resp = http_get(
                "https://api.openalex.org/works",
                params={
                    "filter": (
                        f"title_and_abstract.search:{query},"
                        f"from_publication_date:{since.isoformat()},"
                        "type:article,language:en"
                    ),
                    "sort": "publication_date:desc",
                    "per-page": oa.get("max_per_query", 10),
                    "select": "id,title,publication_date,primary_location,"
                              "doi,abstract_inverted_index,authorships",
                },
            )
            for work in resp.json().get("results", []):
                title_key = re.sub(r"\s+", " ", (work.get("title") or "")).strip().lower()
                if not title_key or title_key in seen_titles:
                    continue
                seen_titles.add(title_key)
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
                    "kind": "openalex",
                    "summary": "",
                    "summary_source": truncate(
                        reconstruct_abstract(work.get("abstract_inverted_index")),
                        1200),
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
                },
            )
            root = ET.fromstring(resp.content)
            # APIのステータスを検査
            # (0=正常, WARN_xxx=警告付きで結果あり, ERR_001=該当0件)
            for elem in root.iter():
                if strip_ns(elem.tag) == "status":
                    status = (elem.text or "").strip()
                    if status == "ERR_001":  # 検索結果なし
                        break
                    if status and status != "0" and not status.startswith("WARN"):
                        raise RuntimeError(f"J-STAGE APIエラー: {status}")
                    break
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
                    "kind": "jstage",
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


def strip_html(text):
    """HTMLタグを除去してプレーンテキストにする。"""
    import html as html_mod
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html_mod.unescape(text)).strip()


def parse_feed_entries(content):
    """フィードXMLから (title, link, published, description) のリストを返す。"""
    root = ET.fromstring(content)
    entries = []
    for elem in root.iter():
        if strip_ns(elem.tag) not in ("item", "entry"):
            continue
        title, link, published, desc = "", "", None, ""
        for child in elem:
            tag = strip_ns(child.tag)
            text = (child.text or "").strip()
            if tag == "title" and text:
                title = text
            elif tag == "link":
                link = link or child.get("href") or text
            elif tag in ("pubDate", "date", "updated", "published", "issued"):
                published = published or parse_feed_date(text)
            elif tag in ("description", "summary", "content"):
                desc = desc or strip_html(text)
        entries.append((title, link, published, desc))
    return entries


def collect_feeds(cfg, since):
    """フィードごとに {"category": ..., "items": [...] or None(失敗)} を返す。"""
    grouped, errors = {}, []
    for feed_cfg in cfg.get("feeds", []):
        name = feed_cfg.get("name", feed_cfg.get("url", "feed"))
        category = feed_cfg.get("category", "public")
        keywords = [str(k).lower() for k in (feed_cfg.get("keywords") or [])]
        try:
            resp = http_get(feed_cfg["url"], params=feed_cfg.get("params"))
            found = []
            for title, link, published, desc in parse_feed_entries(resp.content):
                if not title:
                    continue
                if keywords and not any(k in title.lower() for k in keywords):
                    continue
                # 日付が取れて期間外なら除外。日付が無い場合は seen.json に任せる
                if published and published < since:
                    continue
                # 説明文がタイトルの繰り返しでなければ要約の元テキストにする
                source_text = desc if desc and desc not in title \
                    and title not in desc else ""
                found.append({
                    "id": link or f"{name}:{title}",
                    "title": title,
                    "url": link,
                    "date": published.isoformat() if published else "",
                    "venue": name,
                    "authors": "",
                    "summary": "",
                    "summary_source": truncate(source_text, 1200),
                })
            grouped[name] = {"category": category, "items": found}
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {exc}")
            grouped[name] = {"category": category, "items": None}  # 取得失敗
    return grouped, errors


# ----------------------------------------------------------------------
# トレンド抽出と論文選定
# ----------------------------------------------------------------------

def item_text(item):
    return (item.get("title", "") + " " + item.get("summary_source", "")).lower()


def match_keywords(item, keywords):
    """アイテムにマッチするトレンドラベルのリストを返す。"""
    text = item_text(item)
    return [label for label, variants in keywords.items()
            if any(str(v).lower() in text for v in variants)]


def extract_trends(articles, cfg):
    """新聞・業界誌記事からトレンドキーワードを集計し [(ラベル, 記事数)] を返す。"""
    tr = cfg.get("trends") or {}
    keywords = tr.get("keywords") or {}
    counts = {}
    for article in articles:
        for label in match_keywords(article, keywords):
            counts[label] = counts.get(label, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return ranked[: int(tr.get("top_n", 5))]


def select_papers(papers, trends, cfg):
    """トレンドとの関連度で論文をスコアリングし、上位 limit 件を返す。

    スコア = トレンド上位ほど大きい重み × マッチ数。トレンド外でも
    辞書内キーワードとの一致は小さく加点。同点は発行日の新しい順。
    """
    limit = int((cfg.get("papers") or {}).get("limit", 3))
    keywords = (cfg.get("trends") or {}).get("keywords") or {}
    trend_weight = {label: len(trends) - i for i, (label, _) in enumerate(trends)}
    scored = []
    for paper in papers:
        matched = match_keywords(paper, keywords)
        score = sum(trend_weight.get(label, 0) * 10 + 1 for label in matched)
        paper["trend_labels"] = [l for l in matched if l in trend_weight]
        scored.append((score, paper))
    scored.sort(key=lambda sp: sp[1].get("date", ""), reverse=True)
    scored.sort(key=lambda sp: sp[0], reverse=True)
    return [paper for _, paper in scored[:limit]]


# ----------------------------------------------------------------------
# 要約: J-STAGE抄録の取得 + GitHub Models(無料AI)による日本語要約
# ----------------------------------------------------------------------

def fetch_jstage_abstract(url):
    """J-STAGE論文ページのmetaタグから抄録テキストを取得する。"""
    try:
        html = http_get(url).content.decode("utf-8", errors="replace")
        for tag_str in re.findall(r"<meta\b[^>]*>", html):
            attrs = dict(re.findall(r'([\w:-]+)\s*=\s*"([^"]*)"', tag_str))
            key = attrs.get("name") or attrs.get("property") or ""
            if key in ("description", "og:description",
                       "citation_abstract", "twitter:description"):
                text = strip_html(attrs.get("content", ""))
                if len(text) >= 60:  # サイト共通の短い説明文は抄録ではない
                    return truncate(text, 1200)
    except Exception:  # noqa: BLE001 - 抄録が取れなくても収集は続行
        pass
    return ""


def enrich_jstage_abstracts(items):
    for item in items:
        if item.get("url") and not item.get("summary_source"):
            item["summary_source"] = fetch_jstage_abstract(item["url"])


def summarize_items(all_items, cfg):
    """summary_source を持つアイテムに日本語1〜2文の要約(summary)を付ける。

    GitHub Actions の GITHUB_TOKEN で使える GitHub Models(無料)を利用。
    トークンが無い/失敗した場合は原文の抜粋にフォールバックする。
    """
    import os
    sm = cfg.get("summarize") or {}
    targets = [it for it in all_items
               if it.get("summary_source") and not it.get("summary")]
    if not targets:
        return []
    errors = []
    token = os.environ.get("GITHUB_TOKEN", "")
    if sm.get("enabled", True) and token:
        chunk_size = int(sm.get("chunk_size", 15))
        model = sm.get("model", "openai/gpt-4o-mini")
        for start in range(0, len(targets), chunk_size):
            chunk = targets[start:start + chunk_size]
            payload = [{"i": str(i), "text": truncate(it["summary_source"], 700)}
                       for i, it in enumerate(chunk)]
            prompt = (
                "以下のJSON配列の各textは、論文の抄録またはニュースの本文抜粋です。"
                "それぞれを日本語1〜2文(100文字程度まで)で要約してください。"
                "英語など外国語の場合も必ず日本語で要約すること。"
                "出力は、キーが各項目の\"i\"の値・値が要約文であるJSONオブジェクト"
                "のみを返してください。\n\n"
                + json.dumps(payload, ensure_ascii=False)
            )
            try:
                resp = requests.post(
                    "https://models.github.ai/inference/chat/completions",
                    headers={"Authorization": f"Bearer {token}",
                             "Content-Type": "application/json",
                             "User-Agent": USER_AGENT},
                    json={"model": model, "temperature": 0.2, "messages": [
                        {"role": "system",
                         "content": "あなたは学術論文とニュースの要約担当です。"},
                        {"role": "user", "content": prompt}]},
                    timeout=120,
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                content = re.sub(r"^```(json)?\s*|\s*```$", "",
                                 content.strip(), flags=re.M).strip()
                result = json.loads(content)
                for i, it in enumerate(chunk):
                    summary = result.get(str(i))
                    if summary:
                        it["summary"] = truncate(str(summary), 300)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"AI要約(第{start // chunk_size + 1}バッチ): {exc}")
    # フォールバック: 要約が付かなかったものは原文の冒頭を載せる
    for it in targets:
        if not it["summary"]:
            it["summary"] = truncate(it["summary_source"], 200)
    return errors


# ----------------------------------------------------------------------
# 重複排除(seen.json)
# ----------------------------------------------------------------------

def load_seen(path):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def drop_seen(items, seen):
    """既出アイテムを除外する(seenへの記録はしない)。"""
    return [item for item in items if item["id"] not in seen]


def mark_seen(items, seen, today):
    for item in items:
        seen[item["id"]] = today.isoformat()


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
        lines.append(f"- 要約: {item['summary']}")
    return "\n".join(lines)


def render_feed_sections(lines, feed_groups, category):
    for name, group in feed_groups.items():
        if group["category"] != category:
            continue
        items = group["items"]
        if items is None:
            lines.append(f"### {name}")
            lines.append("⚠️ 取得に失敗しました(config/sources.yml のURLを確認してください)。")
            lines.append("")
            continue
        lines.append(f"### {name}({len(items)}件)")
        if items:
            for item in items:
                link = f" — <{item['url']}>" if item["url"] else ""
                d = f"({item['date']}) " if item["date"] else ""
                lines.append(f"- {d}{item['title']}{link}")
                if item.get("summary"):
                    lines.append(f"  - 要約: {item['summary']}")
        else:
            lines.append("- 新着はありませんでした。")
        lines.append("")


def count_feed_items(feed_groups):
    return sum(len(g["items"]) for g in feed_groups.values()
               if g["items"] is not None)


def render_report(today, since, trends, papers, feed_groups, errors):
    total = len(papers) + count_feed_items(feed_groups)
    lines = [
        f"# 人事研究デイリーレポート {today.isoformat()}",
        "",
        f"収集期間: {since.isoformat()} 〜 {today.isoformat()} / "
        f"新着 **{total} 件**",
        "",
        "収集元は国内外の学術論文(OpenAlex・J-STAGE)、業界誌、新聞、"
        "公的機関に限定しています。",
        "",
    ]

    lines.append("## 🔥 本日のトレンド")
    lines.append("")
    if trends:
        lines.append("直近の新聞・業界誌記事で取り上げられたキーワードの集計です。")
        lines.append("")
        for rank, (label, count) in enumerate(trends, 1):
            lines.append(f"{rank}. **{label}**({count}記事)")
    else:
        lines.append("トレンドを判定できる記事がありませんでした。")
    lines.append("")

    lines.append(f"## 📄 注目論文({len(papers)}件)")
    lines.append("")
    lines.append("収集した国内外の論文から、トレンドとの関連度が高い順に選定しています。")
    lines.append("")
    if papers:
        for item in papers:
            lines.append(render_item(item))
            if item.get("trend_labels"):
                lines.append(f"- 関連トレンド: {'、'.join(item['trend_labels'])}")
            lines.append("")
    else:
        lines.append("新着論文はありませんでした。")
        lines.append("")

    lines.append("## 📰 新聞")
    lines.append("")
    render_feed_sections(lines, feed_groups, "news")

    lines.append("## 📚 業界誌")
    lines.append("")
    render_feed_sections(lines, feed_groups, "industry")

    lines.append("## 🏛 公的機関・研究機関")
    lines.append("")
    render_feed_sections(lines, feed_groups, "public")

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
    today = datetime.now(JST).date()
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

    # 論文は「既出でないもの」を候補にし、掲載に選ばれたものだけ既出扱いにする
    # (選ばれなかった論文は翌日以降トレンドが変われば選ばれ得る)
    candidates = drop_seen(openalex_items, seen) + drop_seen(jstage_items, seen)
    # 複数の検索クエリに同じ論文がヒットするためIDで重複除去
    unique = {}
    for paper in candidates:
        unique.setdefault(paper["id"], paper)
    candidates = list(unique.values())
    for group in feed_groups.values():
        if group["items"] is not None:
            group["items"] = filter_new(group["items"], seen, today)

    # トレンド抽出(新聞・業界誌の新着記事から)→ 論文をトレンド連動で選定
    articles = [item for group in feed_groups.values()
                if group["category"] in ("news", "industry") and group["items"]
                for item in group["items"]]
    trends = extract_trends(articles, cfg)
    papers = select_papers(candidates, trends, cfg)
    mark_seen(papers, seen, today)

    # 掲載が決まったものだけ抄録取得とAI要約を行う
    enrich_jstage_abstracts([p for p in papers if p.get("kind") == "jstage"])
    all_items = list(papers)
    for group in feed_groups.values():
        if group["items"]:
            all_items += group["items"]
    all_errors += summarize_items(all_items, cfg)

    report = render_report(today, since, trends, papers,
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

    total = len(papers) + count_feed_items(feed_groups)
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
