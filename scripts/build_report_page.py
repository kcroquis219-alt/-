#!/usr/bin/env python3
"""reports/*.md を1枚のHTMLページ(Claudeアーティファクト用)にまとめる。

使い方:
  python scripts/build_report_page.py -o /path/to/page.html

日付ごとのレポートを左のナビで切り替えて読める、蓄積型の閲覧ページを生成する。
"""

import argparse
import html
import re
from pathlib import Path

MAX_REPORTS = 60  # ページに含める最大日数(古いものはGitHub側で閲覧)


def inline_md(text):
    """エスケープ済みテキストにインライン装飾(太字・リンク)を適用する。"""
    text = html.escape(text, quote=False)
    text = re.sub(r"&lt;(https?://[^&\s]+)&gt;",
                  r'<a href="\1" target="_blank" rel="noopener">\1</a>', text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    return text


def md_to_html(md):
    """レポートで使う範囲のMarkdownをHTMLへ変換する(見出し・リスト・段落)。"""
    out = []
    stack = []  # 開いているリストのインデント深さ

    def close_lists(depth=-1):
        while stack and stack[-1] > depth:
            out.append("</ul>")
            stack.pop()

    for raw in md.splitlines():
        line = raw.rstrip()
        if not line.strip():
            close_lists()
            continue
        m = re.match(r"^(#{1,3}) (.*)$", line)
        if m:
            close_lists()
            level = len(m.group(1))
            if level == 1:
                continue  # レポート先頭のH1はセクション見出しと重複するため省略
            out.append(f"<h{level + 1}>{inline_md(m.group(2))}</h{level + 1}>")
            continue
        m = re.match(r"^(\s*)- (.*)$", line)
        if m:
            depth = len(m.group(1))
            if not stack or depth > stack[-1]:
                out.append("<ul>")
                stack.append(depth)
            else:
                close_lists(depth)
                if not stack or stack[-1] < depth:
                    out.append("<ul>")
                    stack.append(depth)
            out.append(f"<li>{inline_md(m.group(2))}</li>")
            continue
        m = re.match(r"^(\d+)\. (.*)$", line)
        if m:
            close_lists()
            out.append(f'<p class="ranked"><span class="rank">{m.group(1)}</span> '
                       f"{inline_md(m.group(2))}</p>")
            continue
        close_lists()
        out.append(f"<p>{inline_md(line)}</p>")
    close_lists()
    return "\n".join(out)


PAGE = """<title>人事研究デイリー</title>
<style>
:root {
  --bg: #f6f8f7; --surface: #ffffff; --ink: #1f2a2e; --muted: #5c6b70;
  --accent: #0e6e6b; --accent-ink: #ffffff; --line: #dde3e1; --chip: #e8efed;
}
:root:not([data-theme="light"]) { }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #14191b; --surface: #1c2326; --ink: #e4e9e8; --muted: #94a3a6;
    --accent: #56b8b2; --accent-ink: #0e1a19; --line: #2a3438; --chip: #223034;
  }
}
:root[data-theme="dark"] {
  --bg: #14191b; --surface: #1c2326; --ink: #e4e9e8; --muted: #94a3a6;
  --accent: #56b8b2; --accent-ink: #0e1a19; --line: #2a3438; --chip: #223034;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--ink);
  font-family: "Hiragino Kaku Gothic ProN", "Hiragino Sans", "Yu Gothic",
               "Noto Sans JP", "Meiryo", sans-serif;
  line-height: 1.75; font-size: 15px;
}
header.site {
  border-bottom: 1px solid var(--line); background: var(--surface);
  padding: 20px 24px;
}
header.site h1 { margin: 0; font-size: 19px; letter-spacing: .02em; }
header.site h1 span { color: var(--accent); }
header.site p { margin: 4px 0 0; color: var(--muted); font-size: 12.5px; }
.wrap { display: flex; gap: 0; max-width: 1080px; margin: 0 auto; }
nav.dates {
  flex: 0 0 168px; border-right: 1px solid var(--line);
  padding: 16px 0; position: sticky; top: 0; align-self: flex-start;
  max-height: 100vh; overflow-y: auto;
}
nav.dates .label {
  font-size: 11px; letter-spacing: .12em; color: var(--muted);
  padding: 0 20px 8px; text-transform: uppercase;
}
nav.dates button {
  display: block; width: 100%; text-align: left; border: 0;
  background: none; color: var(--ink); font: inherit;
  font-variant-numeric: tabular-nums; font-size: 13.5px;
  padding: 7px 20px; cursor: pointer; border-left: 3px solid transparent;
}
nav.dates button:hover { background: var(--chip); }
nav.dates button.active {
  border-left-color: var(--accent); color: var(--accent); font-weight: 700;
  background: var(--chip);
}
nav.dates button:focus-visible, select:focus-visible, a:focus-visible {
  outline: 2px solid var(--accent); outline-offset: 2px;
}
main { flex: 1; min-width: 0; padding: 28px 32px 64px; }
main .report { display: none; max-width: 72ch; }
main .report.active { display: block; }
.report-head { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.report-head h2 {
  margin: 0; font-size: 24px; letter-spacing: .01em; text-wrap: balance;
  font-variant-numeric: tabular-nums;
}
.report-head .dow {
  color: var(--muted); font-size: 13px;
}
.report h3 {
  margin: 32px 0 10px; font-size: 16.5px; padding-bottom: 6px;
  border-bottom: 2px solid var(--line);
}
.report h4 { margin: 20px 0 6px; font-size: 14.5px; color: var(--accent); }
.report p { margin: 8px 0; }
.report p.ranked { margin: 4px 0; }
.report .rank {
  display: inline-block; min-width: 1.6em; text-align: center;
  background: var(--chip); color: var(--accent); border-radius: 4px;
  font-weight: 700; font-variant-numeric: tabular-nums; margin-right: 4px;
}
.report ul { margin: 6px 0; padding-left: 22px; }
.report li { margin: 4px 0; }
.report a { color: var(--accent); word-break: break-all; text-decoration-thickness: 1px; }
.report strong { font-weight: 700; }
.mobile-nav { display: none; padding: 14px 20px 0; }
.mobile-nav select {
  width: 100%; padding: 10px 12px; font: inherit; color: var(--ink);
  background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
}
footer.site {
  border-top: 1px solid var(--line); color: var(--muted);
  font-size: 12px; padding: 16px 24px; text-align: center;
}
footer.site a { color: var(--accent); }
@media (max-width: 720px) {
  nav.dates { display: none; }
  .mobile-nav { display: block; }
  main { padding: 20px 20px 48px; }
}
@media (prefers-reduced-motion: no-preference) {
  main .report.active { animation: fadein .18s ease-out; }
  @keyframes fadein { from { opacity: 0; } to { opacity: 1; } }
}
</style>
<header class="site">
  <h1>人事研究デイリー<span>｜</span>蓄積アーカイブ</h1>
  <p>平日朝7時に自動収集: トレンド → 注目論文3件 → 新聞・業界誌・公的機関(全__COUNT__日分)</p>
</header>
<div class="mobile-nav">
  <select id="dateSelect" aria-label="日付を選択">__OPTIONS__</select>
</div>
<div class="wrap">
  <nav class="dates" aria-label="日付ナビゲーション">
    <div class="label">Reports</div>
    __NAV__
  </nav>
  <main>
    __SECTIONS__
  </main>
</div>
<footer class="site">
  生成元: GitHubリポジトリの reports/ フォルダ ｜ 毎平日朝に自動更新
</footer>
<script>
(function () {
  var buttons = Array.prototype.slice.call(document.querySelectorAll("nav.dates button"));
  var select = document.getElementById("dateSelect");
  function show(date) {
    document.querySelectorAll("main .report").forEach(function (s) {
      s.classList.toggle("active", s.dataset.date === date);
    });
    buttons.forEach(function (b) {
      b.classList.toggle("active", b.dataset.date === date);
    });
    if (select.value !== date) select.value = date;
    if (history.replaceState) history.replaceState(null, "", "#" + date);
    window.scrollTo(0, 0);
  }
  buttons.forEach(function (b) {
    b.addEventListener("click", function () { show(b.dataset.date); });
  });
  select.addEventListener("change", function () { show(select.value); });
  var initial = location.hash.replace("#", "");
  if (!document.querySelector('main .report[data-date="' + initial + '"]')) {
    initial = document.querySelector("main .report").dataset.date;
  }
  show(initial);
})();
</script>
"""

DOW_JA = ["月", "火", "水", "木", "金", "土", "日"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-o", "--out", required=True)
    parser.add_argument("--reports", default="reports")
    args = parser.parse_args()

    from datetime import date as date_cls
    files = sorted(Path(args.reports).glob("*.md"), reverse=True)[:MAX_REPORTS]
    if not files:
        raise SystemExit("reports/ にレポートがありません")

    nav, options, sections = [], [], []
    for path in files:
        d = path.stem  # YYYY-MM-DD
        try:
            y, m, dd = (int(x) for x in d.split("-"))
            dow = DOW_JA[date_cls(y, m, dd).weekday()]
            label = f"{m}/{dd}({dow})"
        except ValueError:
            dow, label = "", d
        nav.append(f'<button data-date="{d}">{d}</button>')
        options.append(f'<option value="{d}">{label} {d}</option>')
        body = md_to_html(path.read_text(encoding="utf-8"))
        sections.append(
            f'<section class="report" data-date="{d}">'
            f'<div class="report-head"><h2>{d}</h2>'
            f'<span class="dow">{label}</span></div>{body}</section>'
        )

    page = (PAGE
            .replace("__COUNT__", str(len(files)))
            .replace("__NAV__", "\n    ".join(nav))
            .replace("__OPTIONS__", "".join(options))
            .replace("__SECTIONS__", "\n    ".join(sections)))
    Path(args.out).write_text(page, encoding="utf-8")
    print(f"page={args.out} reports={len(files)}")


if __name__ == "__main__":
    main()
