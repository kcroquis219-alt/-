# このリポジトリについて

このリポジトリには2つの独立したプロジェクトが同居しています。

1. **感謝の一文字 — 結婚式Web演出**(`index.html`, `config.js`, `data/` ほか)
2. **人事研究 自動収集システム**(`config/sources.yml`, `scripts/collect_hr_research.py`, `reports/` ほか)

---

# 感謝の一文字 — 結婚式Web演出（17卓対応）

2026年8月1日・マリゾン福岡。ゲスト91名・17卓（A〜Q）それぞれに向けた
「感謝の一文字」漢字メッセージのWeb演出です。

卓ごとのQRコードを読み取ると `https://<ドメイン>/?t=A` のように
**同一ページ・パラメータ違い**のURLが開き、その卓のゲスト一覧が表示されます。
解禁時刻前はカウントダウン、解禁後は名前カード（タップで漢字アニメーション）が出ます。

## ファイル構成

| ファイル | 役割 | 編集する？ |
|---|---|---|
| `index.html` | 全卓共通のテンプレート（デザイン本体） | 基本しない |
| `config.js` | **解禁時刻**・署名・会場写真などの設定 | ✏️ する |
| `data/guests.csv` | **91名分のデータ入力用CSV** | ✏️ する |
| `data.js` | CSVから自動生成されるデータ（直接編集しない） | しない |
| `scripts/build_data.py` | CSV → data.js 変換スクリプト | しない |
| `scripts/make_qr.py` | QRコード17枚の一括生成 | しない |

## ゲストデータの入れ方

1. `data/guests.csv` を編集する（Excel / Googleスプレッドシートで開いてCSV保存でOK。1行=1名）

   ```csv
   table_id,guest_name,kanji,yomi,message
   A,山田 太郎,山,やま,どっしりと構えて、いつも私たちを見守ってくれる...
   ```

   - `table_id` は A〜Q
   - メッセージ内で改行したい場合はセルを `"..."` で囲んで改行を入れる

2. 変換スクリプトを実行する

   ```bash
   python3 scripts/build_data.py
   ```

   空欄や不正な卓IDがあるとエラーで教えてくれます。成功すると卓ごとの人数が表示されるので、
   合計91名になっているか確認してください。

3. 生成された `data.js` ごとコミット＆プッシュ

## 解禁時刻の変更

`config.js` の先頭だけ編集すれば全卓に反映されます。

```js
unlockTime:  '2026-08-01T13:00:00+09:00',
unlockLabel: '8月1日 13:00',
```

卓ごとに変えたい場合は `tableOverrides` に追記します（例はファイル内コメント参照）。

## 動作確認（解禁前でも中身を見る）

URLに `&preview` を付けると、解禁時刻前でもカード一覧を確認できます。

```
https://<ドメイン>/?t=A&preview
```

ローカルで確認する場合はリポジトリ直下で:

```bash
python3 -m http.server 8000
# → http://localhost:8000/?t=A&preview
```

## 端末時計の操作対策について

`config.js` の `useServerTime: true`（デフォルト有効）で、配信サーバー
（GitHub Pages等）の時刻を基準に解禁を判定します。ゲストがスマホの時計を
進めても解禁前に中身は見えません。オフライン時やローカルで開いた場合は
自動で端末時計にフォールバックします。
※ `&preview` を知っていれば見えてしまうので、パラメータ付きURLは配らないでください。

## 公開（GitHub Pages）

1. このリポジトリをGitHubにプッシュ
2. リポジトリの **Settings → Pages → Branch: main（root）** を選んで保存
3. 数分後 `https://<ユーザー名>.github.io/<リポジトリ名>/` で公開されます
4. データ更新時は「CSV編集 → `build_data.py` 実行 → コミット＆プッシュ」だけで反映

Netlifyの場合はリポジトリを連携（ビルドコマンドなし・公開ディレクトリ `/`）するだけです。

## QRコードの生成

公開URLが確定したら:

```bash
pip install qrcode pillow
python3 scripts/make_qr.py https://<ユーザー名>.github.io/<リポジトリ名>/
```

`qr/QR_A.png` 〜 `qr/QR_Q.png`（約1200px・誤り訂正レベルQ・
テーマカラーの藍色）が生成されます。4cm角印刷で約750dpi相当なので
印刷品質は十分です。生成後、必ず1枚スマホで読み取りテストをしてください。

## 本番前チェックリスト

- [ ] 91名分のCSV入力完了・`build_data.py` で合計人数を確認
- [ ] `config.js` の解禁時刻が正しい
- [ ] 全卓のURL（`?t=A`〜`?t=Q`）をひととおり開いて名前を確認
- [ ] QRコード17枚を実機で読み取りテスト
- [ ] 解禁前画面（カウントダウン）の表示確認

---

# 人事研究 自動収集システム

**平日 7:00(日本時間)** に、人事(HR)に関する最新の研究・公的調査データ・新聞報道を国内外から自動収集し、Markdownレポートを生成する仕組みです。GitHub Actions 上で完結するため、サーバーの用意や費用は不要です。

## 収集元(信頼できるソースに限定)

個人や企業の根拠が曖昧なコラムを排除するため、収集元を **査読論文データベース・公的機関・新聞報道** に限定しています。

| 区分 | ソース | 内容 |
|---|---|---|
| 海外論文 | [OpenAlex](https://openalex.org) | 世界最大級のオープン学術DB。査読付き論文のみ |
| 国内論文 | [J-STAGE](https://www.jstage.jst.go.jp) | JST運営の国内学術論文プラットフォーム |
| 公的調査 | 厚生労働省 | 雇用・賃金・労働関連の統計/調査の新着 |
| 公的調査 | JILPT(労働政策研究・研修機構) | 労働政策の調査研究成果 |
| 公的調査 | RIETI(経済産業研究所) | 雇用・人材関連のディスカッションペーパー等 |
| 海外研究 | NBER(全米経済研究所) | 労働経済学のワーキングペーパー |
| 新聞報道 | Google News検索(全国紙・通信社等を横断) | 人事・雇用・賃金関連の記事 |
| 新聞報道 | NHKニュース(経済) | 雇用・労働関連の報道 |

## 動作の流れ

1. 平日 7:00 JST に GitHub Actions が起動(手動実行も可能)
2. 各ソースから直近数日の新着を取得し、キーワードでフィルタ
3. 過去に収集済みのものは `data/seen.json` で自動的に重複排除
4. `reports/YYYY-MM-DD.md` にレポートをコミット
5. 同じ内容を **Issue として投稿** → GitHubの通知(メール)で受け取れる

> 📧 メールで受け取りたい場合は、このリポジトリを Watch(All Activity)に設定してください。Issueが作成されるたびに通知が届きます。

## 手動で試す

GitHub の **Actions タブ → 「平日 人事研究レポート」→ Run workflow** で今すぐ実行できます。

ローカルで動かす場合:

```bash
pip install -r requirements.txt
python scripts/collect_hr_research.py
```

## カスタマイズ

検索キーワードや収集元はすべて [`config/sources.yml`](config/sources.yml) で管理しています。

- **検索キーワードの変更**: `openalex.queries`(英語)/ `jstage.queries`(日本語)/ 新聞は `feeds:` の Google News `params.q` を編集
- **収集元の追加**: RSSフィードを `feeds:` に追記(`category: public` か `news` を指定。`keywords` を指定するとタイトルで絞り込み)
- **収集期間の変更**: `window_days` を編集
- **実行タイミングの変更**: [`.github/workflows/daily-hr-research.yml`](.github/workflows/daily-hr-research.yml) の `cron` を編集(UTC表記。JSTから9時間引く)

## トラブルシューティング

- レポートに「⚠️ 取得に失敗しました」と出る場合、そのソースのRSS URLが変更された可能性があります。`config/sources.yml` のURLを最新のものに修正してください(各機関サイトの「RSS」ページで確認できます)。
- スケジュール実行は、リポジトリに60日間活動がないとGitHubにより自動停止されます。Actionsタブから再有効化できます。
