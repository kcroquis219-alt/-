#!/usr/bin/env python3
"""data/guests.csv から data.js を生成する。

使い方:
    python3 scripts/build_data.py

CSVの列: table_id, guest_name, kanji, yomi, message
  - table_id は A〜Q（大文字・小文字どちらでも可）
  - message 内で改行したい場合は、セルを "..." で囲んで実際に改行してよい
  - Excelで保存したCSV（BOM付きUTF-8）にも対応
"""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "guests.csv"
OUT_PATH = ROOT / "data.js"

TABLE_IDS = list("ABCDEFGHIJKLMNOPQ")  # 17卓


def main() -> None:
    tables = {tid: [] for tid in TABLE_IDS}
    errors = []

    with CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"table_id", "guest_name", "kanji", "yomi", "message"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            sys.exit(f"CSVのヘッダー行が不正です。必要な列: {', '.join(sorted(required))}")

        for lineno, row in enumerate(reader, start=2):
            tid = (row["table_id"] or "").strip().upper()
            name = (row["guest_name"] or "").strip()
            if not tid and not name:
                continue  # 空行はスキップ
            if tid not in tables:
                errors.append(f"{lineno}行目: 不明な table_id '{tid}'（A〜Qのみ）")
                continue
            for col in ("guest_name", "kanji", "yomi", "message"):
                if not (row[col] or "").strip():
                    errors.append(f"{lineno}行目 ({name or tid}): '{col}' が空です")
            tables[tid].append({
                "name": name,
                "kanji": (row["kanji"] or "").strip(),
                "yomi": (row["yomi"] or "").strip(),
                "msg": (row["message"] or "").strip(),
            })

    if errors:
        print("入力エラーがあります。修正してから再実行してください:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    body = json.dumps(tables, ensure_ascii=False, indent=2)
    # HTML内に埋め込んでも安全なように念のためエスケープ
    body = body.replace("</", "<\\/")
    OUT_PATH.write_text(
        "/* このファイルは scripts/build_data.py が data/guests.csv から自動生成します。\n"
        "   直接編集せず、CSVを編集して再生成してください。 */\n"
        f"const TABLES = {body};\n",
        encoding="utf-8",
    )

    total = sum(len(v) for v in tables.values())
    print(f"data.js を生成しました（{total}名 / {sum(1 for v in tables.values() if v)}卓にデータあり）")
    for tid in TABLE_IDS:
        print(f"  {tid}: {len(tables[tid])}名")


if __name__ == "__main__":
    main()
