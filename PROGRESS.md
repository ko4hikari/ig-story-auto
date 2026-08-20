# セットアップ進捗

仕様は `SPEC.md`、運用手順は `README.md` を参照。このファイルはセットアップ作業の進捗メモ。

## 完了

### ① コード整備
- `_parse_sheet_date()` にゼロ埋めなし日付（`2026/8/17`）のパースを追加
- `--check` / `--dry-run` がローカルで動作することを確認
- Instagram APIを **Facebookログイン方式**（`graph.facebook.com` + `IG_USER_ID`）に切り替え済み（詳細はREADME §1・§7）
- `content_publishing_limit` 取得時に `fields=quota_usage,config` を明示するよう修正（省略すると判定不能になるバグを修正済み）

### ② Googleスプレッドシート連携
- 休業日シートを作成し、B列プルダウン（`オープンのみ停止` / `全停止`）を設定済み
- A列（日付）に「有効な日付」のデータ入力規則を設定し、カレンダーピッカーで選択できるようにした（手入力も可能）
- 「ウェブに公開」でCSV URLを取得し、Secrets `CLOSED_DAYS_CSV_URL` に設定・動作確認済み
  - `オープンのみ停止` / `全停止` の挙動、`closed_days.txt:N` 表示、キャッシュ書き込みを確認済み

### ③ GitHubリポジトリと画像公開
- public リポジトリ `https://github.com/ko4hikari/ig-story-auto` に push 済み
- `open`（7枚）・`promo`（3枚）とも本番画像に差し替え済み
- promo画像はアスペクト比不一致によるクロップ問題を修正し、1080×1920（9:16、ぼかし背景での余白埋め）に統一済み
- `IMAGE_BASE_URL` は `https://raw.githubusercontent.com/ko4hikari/ig-story-auto/main`

### ④ Instagram / Metaトークン
- Meta Business Suiteでシステムユーザー `igstoryautobot`（ID: `61593695151359`）を作成
- Facebookページ（メタ広告と共用、解除不可）をシステムユーザーに割り当て済み
- システムユーザートークン（60日有効）を発行し `IG_ACCESS_TOKEN` に設定
- `IG_USER_ID`（`17841477742242047`）を確認・設定済み
- **既知の事故と対処**: PowerShellで `Get-Clipboard | gh secret set` のようにパイプ経由で設定すると、値の先頭にBOM文字が混入し壊れることが判明（`IG_ACCESS_TOKEN` と `NOTIFY_WEBHOOK` の両方で発生）。以後は `gh secret set NAME --body $value` 形式に統一

### ⑤ GitHub Actions 手動実行
- `NOTIFY_WEBHOOK` にDiscord Webhook URLを設定し、テスト通知の送信成功を確認
- `workflow_dispatch` で `Slot - promo` を実行し、3枚の本番投稿・CI全体の流れが正常動作することを確認済み（実行ID: `32320207821`）

### ⑥ トークンの有効性チェック
- `refresh-token.yml` を実態（自動リフレッシュAPIが存在しないため、有効性チェックのみ行う設計）に合わせて更新済み
- 旧設計で使っていた `GH_PAT` は不要になったため撤去済み

### ⑦ 投稿時刻の確定
- `open` = 17:00 JST、`promo` = 18:00 JST
- `config.json` と両workflowファイルに反映・push済み

### ⑧ 投稿時刻のズレ対策（2026-08-21）
- 初回の自動実行（cronによる本番投稿）で、両スロットとも予定時刻から約30分遅延して投稿された
- 原因: GitHub Actionsのscheduled workflowは毎時ちょうど（`:00`）に混雑しやすく、遅延することがある（GitHub公式の既知事象）
- 対策: cronの起動時刻を目標時刻の20〜25分前・`:00`以外の分にずらし（open: `35 7 * * *`、promo: `38 8 * * *`）、起動後に「Wait until」ステップでUTC目標時刻ちょうどまで`sleep`してから投稿するよう両workflowを修正・push済み
- 次回のcron自動実行で、実際に時刻ズレが解消されているか要確認

## 次にやること

- **次回の自動投稿（open 17:00 JST / promo 18:00 JST）で、時刻ズレ対策が効いているか確認する**（⑧参照）
- `IG_ACCESS_TOKEN` の60日ごとの手動更新（自動更新なし。README §9参照）
- 長期休業などで `PAUSE` フラグを使う運用が実際に機能するか、次の休業時に確認
- 画像を追加・入れ替える際は9:16比率を保つこと（README §5参照）

## 未確認の受け入れ基準

`SPEC.md` §15 のうち、以下がまだ未確認（実運用の中で自然に確認できるものが多い）。

- 12: A1セルに `PAUSE` を入れると全スロットが止まる
- 7, 8: 投稿数上限の不足時・`all` モード途中失敗時の挙動
- 14, 15: CSV取得失敗時のフォールバック（実URLでの再確認）
- 18: トークン破損時の通知（BOM混入トラブルの際に間接的に確認済み。意図的な破損テストは未実施）

1〜6, 9〜11, 13, 16, 17, 19 はローカル検証・本番投稿の両方で確認済み。
