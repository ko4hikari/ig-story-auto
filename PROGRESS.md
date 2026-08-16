# セットアップ進捗

仕様は `SPEC.md`、運用手順は `README.md` を参照。このファイルはセットアップ作業の進捗メモ。

## 完了

### ① コード整備
- `_parse_sheet_date()` にゼロ埋めなし日付（`2026/8/17`）のパースを追加
- `assets/open/`, `assets/promo/` にダミー画像を2枚ずつ配置（**実運用前に差し替えが必要**）
- `--check` / `--dry-run` がローカルで動作することを確認

### ② Googleスプレッドシート連携
- 休業日シートを作成し、B列プルダウン（`オープンのみ停止` / `全停止`）を設定済み
- 「ウェブに公開」でCSV URLを取得済み（値は Secrets `CLOSED_DAYS_CSV_URL` に入れる。リポジトリには書かない）
- 実URLに対して `--check` を実行し、以下を確認
  - `オープンのみ停止` の日は `open` のみ休業、`promo` は投稿予定のまま
  - `全停止` の日は両スロットとも休業し、メモも表示される
  - 休業行に `closed_days.txt:N` の行番号が出る
  - 取得成功時に `closed_days.txt` へキャッシュが書き込まれる

## 次にやること

### ③ GitHubリポジトリと画像公開
現状: git初期化済み（`master`、コミット0件）。GitHub CLI（`gh`）は未インストール。

1. GitHubに **public** リポジトリを作成（Instagramが認証なしで画像を取得する必要があるため）
2. 初回コミットして push
3. `assets/` のダミー画像を本番用（1080×1920、8MB以下、半角英数字のファイル名）に差し替え
4. raw URL をブラウザで開き、画像が表示されることを確認
5. `IMAGE_BASE_URL` を確定（例: `https://raw.githubusercontent.com/{user}/{repo}/main`、末尾スラッシュなし）

### ④ Instagram / Metaトークン
`README.md` §1 の手順。長期トークン（60日）を取得して `IG_ACCESS_TOKEN` に設定。

### ⑤ GitHub Actions 手動実行
Secrets を設定し、`workflow_dispatch` で `Slot - promo` を実行。投稿・`closed_days.txt` の自動コミット・通知を確認。

### ⑥ トークンリフレッシュ
`GH_PAT`（repoスコープ）を設定し、`refresh-token.yml` を手動実行して確認。

## 未確認の受け入れ基準

`SPEC.md` §15 のうち、以下がまだ未確認。

- 12: A1セルに `PAUSE` を入れると全スロットが止まる
- 7, 8: 投稿数上限の不足時・`all` モード途中失敗時の挙動（実APIが必要）
- 14, 15: CSV取得失敗時のフォールバック（実URLでの再確認）
- 18, 19: トークン破損時の通知、ログへのトークン非出力

1〜6, 9〜11, 13, 16, 17 はローカル検証済み。
