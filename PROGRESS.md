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

### ③ GitHubリポジトリと画像公開（1・2・4のみ完了）
- GitHub CLI 認証済み（アカウント: `ko4hikari`）
- public リポジトリ `https://github.com/ko4hikari/ig-story-auto` を作成し、`main` ブランチに初回コミットを push 済み
- raw URL（4画像すべて）で `HTTP 200` / `Content-Type: image/jpeg` を確認済み（現状はダミー画像のため各39バイト）
  - 例: `https://raw.githubusercontent.com/ko4hikari/ig-story-auto/main/assets/open/01.jpg`
- `IMAGE_BASE_URL` は `https://raw.githubusercontent.com/ko4hikari/ig-story-auto/main`（末尾スラッシュなし）で確定

### promo 画像の本番差し替え
- ダミー画像（`01.jpg`, `02.jpg`）を削除し、本番用3枚に差し替え済み
  - `01_yoru.jpg` → `02_chinsuko.jpg` → `03_fruit_shisha.jpg` の順（追加順）で投稿される
  - 解像度は1080×1920（9:16）ではなく853×1844 / 1078×1518 / 1114×1470。投稿自体は可能だが、Instagram側でレターボックスが入る可能性あり（未確認・要実機チェック）
- raw URLで3枚とも表示確認済み

### open 画像の本番差し替え
- ダミー画像（`01.jpg`, `02.jpg`）を削除し、本番用7枚（`S__212557827_0.jpg`〜`S__212557833_0.jpg`）に差し替え済み
  - 960×1706（9:16相当、比率0.5627）で理想的な比率。ファイル名も半角英数字のためリネーム不要
  - `rotate` モードなので投稿順は日付依存（並び順そのものは意味を持たない）
- raw URLで7枚とも `HTTP 200` を確認済み

## 次にやること

### ③ 完了
GitHubリポジトリ作成・push・raw URL公開・open/promo両方の本番画像差し替えまで完了。

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
