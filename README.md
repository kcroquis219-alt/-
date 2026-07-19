# 人事研究 自動収集システム

**毎週月曜 9:00(日本時間)** に、人事(HR)に関する最新の研究・公的調査データを国内外から自動収集し、Markdownレポートを生成する仕組みです。GitHub Actions 上で完結するため、サーバーの用意や費用は不要です。

## 収集元(信頼できるソースに限定)

個人や企業の根拠が曖昧なコラムを排除するため、収集元を **査読論文データベースと公的機関** に限定しています。

| 区分 | ソース | 内容 |
|---|---|---|
| 海外論文 | [OpenAlex](https://openalex.org) | 世界最大級のオープン学術DB。査読付き論文のみ |
| 国内論文 | [J-STAGE](https://www.jstage.jst.go.jp) | JST運営の国内学術論文プラットフォーム |
| 公的調査 | 厚生労働省 | 雇用・賃金・労働関連の統計/調査の新着 |
| 公的調査 | JILPT(労働政策研究・研修機構) | 労働政策の調査研究成果 |
| 公的調査 | RIETI(経済産業研究所) | 雇用・人材関連のディスカッションペーパー等 |
| 海外研究 | NBER(全米経済研究所) | 労働経済学のワーキングペーパー |

## 動作の流れ

1. 毎週月曜 9:00 JST に GitHub Actions が起動(手動実行も可能)
2. 各ソースから直近1週間の新着を取得し、キーワードでフィルタ
3. 過去に収集済みのものは `data/seen.json` で自動的に重複排除
4. `reports/YYYY-MM-DD.md` にレポートをコミット
5. 同じ内容を **Issue として投稿** → GitHubの通知(メール)で受け取れる

> 📧 メールで受け取りたい場合は、このリポジトリを Watch(All Activity)に設定してください。Issueが作成されるたびに通知が届きます。

## 手動で試す

GitHub の **Actions タブ → 「週次 人事研究レポート」→ Run workflow** で今すぐ実行できます。

ローカルで動かす場合:

```bash
pip install -r requirements.txt
python scripts/collect_hr_research.py
```

## カスタマイズ

検索キーワードや収集元はすべて [`config/sources.yml`](config/sources.yml) で管理しています。

- **検索キーワードの変更**: `openalex.queries`(英語)/ `jstage.queries`(日本語)を編集
- **収集元の追加**: 公的機関のRSSフィードを `feeds:` に追記(`keywords` を指定するとタイトルで絞り込み)
- **収集期間の変更**: `window_days` を編集
- **実行タイミングの変更**: [`.github/workflows/weekly-hr-research.yml`](.github/workflows/weekly-hr-research.yml) の `cron` を編集(UTC表記。JSTから9時間引く)

## トラブルシューティング

- レポートに「⚠️ 取得に失敗しました」と出る場合、そのソースのRSS URLが変更された可能性があります。`config/sources.yml` のURLを最新のものに修正してください(各機関サイトの「RSS」ページで確認できます)。
- スケジュール実行は、リポジトリに60日間活動がないとGitHubにより自動停止されます。Actionsタブから再有効化できます。
