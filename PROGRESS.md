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

### ⑨ 起動の二重化と死活監視（2026-08-27〜28）
- **事故（3つ重なっていた）**:
  1. **GitHub Actions が約11時間遅延**: open は 07:35 UTC 起動予定が実際 18:22 UTC（03:22 JST 28日）、promo も 04:13 JST に起動。発火漏れではなく極端な遅延だった
  2. **Instagram APIがアクセス拒否**: 遅れて起動後、投稿が `status 400 "API access blocked." OAuthException code 200` で失敗（open/promo 両方）。→ 調査の結果、**`IG_ACCESS_TOKEN`（システムユーザートークン）が無効化されていた**。Metaアプリ `level-story-auto`（ID 1337623905118660）自体は正常（制限・必要なアクション・アラートなし）、システムユーザー `igstoryautobot` のアセット割り当ても正常。グラフAPIエクスプローラーで新規発行したトークンでは同じエンドポイントが正常応答した。トークンは発行から約11日で60日期限には遠く、Meta側のセキュリティイベント（FBパスワード変更・不審ログイン等）かトークン取り消しで失効した可能性が高い
  3. **失敗通知ステップが Discord に 403**: 追加した `if: failure()` ステップが `urllib` 使用で Discord に弾かれていた（`requests` に修正済み・`1e4c649`）。3時に届いた「投稿失敗」通知は `post_story.py` の `notify()`（`requests`使用）が正常に飛んだもの
- **対応が必要（ユーザー作業・最優先）**: システムユーザー `igstoryautobot` から新トークンを生成し `IG_ACCESS_TOKEN` を更新する（Business Suite → 設定 → システムユーザー → トークンを生成 → アプリ `level-story-auto`、権限: instagram_basic / instagram_content_publish / pages_show_list / pages_read_engagement / business_management）。これが直るまで cron/監視を整えても投稿はできない
- **対策（コード側・実装済み・要push）**:
  - `post_story.py` に `last_post.json`（スロット別の最終投稿日）を追加し、同日の二重投稿を防止（外部cronとGitHub cronの併用を可能にした）
  - `post_story.py` に healthchecks.io への死活ping（`HEALTHCHECK_URL` 環境変数）を追加。成功・意図的スキップ時に成功ping、異常時に `/fail` ping
  - 両 workflow に `if: failure()` の失敗通知ステップを追加（`pip install` 失敗やPython未捕捉例外もDiscordに飛ぶ）
  - 両 workflow の commit ステップを `closed_days.txt last_post.json` の両方対象に変更
- **対応済み（2026-08-28）**:
  - `IG_ACCESS_TOKEN` を新トークンに更新。`--refresh-token` に投稿系API（`content_publishing_limit`）チェックを追加し、`/me` だけでなく投稿権限まで検証。手動実行で「有効・投稿系API正常（残り100）」を確認
  - 失敗通知ステップを `urllib` → `requests` に修正（`1e4c649`）。`refresh-token.yml` に `IG_USER_ID` 追加（`f03e31a`）
  - **cron-job.org**: ジョブ2つ作成（`ig-story open` 16:50 JST / `ig-story promo` 17:50 JST）。`workflow_dispatch` API を POST。両方「試運転」で **HTTP 204** を確認済み（＝GitHubが正常受理）。GitHub PATの有効期限は **2027-08-26**（カレンダー登録推奨）
  - **healthchecks.io**: チェック2つ作成（`ig-story-open` cron `0 17 * * *` / `ig-story-promo` cron `0 18 * * *`、いずれも TZ Asia/Tokyo・Grace 45分）。ping URL を Secrets `HEALTHCHECK_URL_OPEN` / `HEALTHCHECK_URL_PROMO` に登録済み。初期pingでアラート有効化済み。通知先は現状メール（`liyibinsnke@gmail.com`）。**Discord連携（「Connect Discord」のOAuth）は未実施**
- **未確認**: 次回の自動投稿（17:00/18:00 JST）で、二重投稿防止・healthchecks成功ping・全体の流れが想定どおり動くか

### ⑩ 仕上げ（2026-08-28）
- **healthchecks.io の Discord連携完了**: `Discord` integration を追加し2チェック両方に割り当て。意図的に `/fail` ping して Discord・メール両方で「DOWN」通知の配信成功を実証（その後復旧）
- **GitHub PAT 作り直し完了**: 旧トークン（チャット露出）を新トークン（`github_pat_11BK3NVHA0zhN05j6H8O6V_...`、期限は要確認）に差し替え。cron-job.org 両ジョブの試運転で HTTP 204 を確認後、旧トークンを Revoke。旧トークンで `gh api` → `401 Bad credentials` を確認済み

### ⑪ トークン再失効と遅延発火対策・本番稼働確認（2026-08-29）
- **事故**: 8/27・8/28 の自動投稿が失敗。通知は `[promo] 投稿数上限の取得に失敗… OAuthException code:190 subcode:463 "Session has expired on 27-Aug-26 18:00 PDT"`。＝`IG_ACCESS_TOKEN` が **60日期限で失効**（⑨で更新した際「無期限」が選べず「60日間」で発行していた）。ユーザーが見た `pip config set … pypi.flatt.tech` は無関係（Takumi Guard というPyPIセキュリティproxyの案内。本プロジェクトでは未使用）
- **対応**:
  - システムユーザー `igstoryautobot` から新トークンを再発行（またも「60日間」）。アクセス許可は既存の5件をそのまま。`gh secret set IG_ACCESS_TOKEN --body …` で更新。「Check IG Access Token」手動実行で「有効・投稿系API正常（残り100）」を確認
  - **次回失効: 2026-10-28 00:49 JST**（`debug_token` API で確認）
  - `post_story.py` に `check_token_expiry()` を追加。`--refresh-token`（週次）で `debug_token` の `expires_at` を見て、**残り `TOKEN_EXPIRY_WARN_DAYS`（=10）日以内なら Discord に警告通知**（`expires_at=0`＝無期限なら通知しない）。→ 10/18頃から警告が飛ぶ想定
  - README §9 を修正（「実質無期限で失効しない」は誤り。選んだ期限で失効する／システムユーザーページのURLを `business.facebook.com/settings/system-users` に訂正）
- **GitHub内蔵cronの遅延発火とその対策**:
  - 8/29 04:33 JST（`35 7 * * *` = 16:35 JST予定が **約12時間遅延**）に `Slot - open` が `schedule` で発火し、待機ステップを素通りして深夜に本番投稿された。ユーザーが手動削除
  - 各 slot workflow 冒頭に `Skip if already posted today or too late` ステップを追加。`git fetch` で最新 `origin/main` の `last_post.json` を見て判定し、次のどちらかで待機・投稿を丸ごとスキップ:
    1. 本日分が投稿済み（二重起動の2回目。Actions時間の節約）
    2. `event=schedule` かつ予定時刻から1時間超の遅延（その頃には手動投稿済みのため）。`workflow_dispatch`（手動・外部cron）は対象外
  - 深夜投稿分を手動削除して定刻分を通すため、`last_post.json` を `{}` にリセットして push
- **テスト用ワークフロー追加**: `test-dry-run.yml`（手動実行のみ）。実Secretsで `--check` / `--dry-run` / 画像URLのHTTP200確認 / `--refresh-token` をまとめて実行。投稿は一切しない
- **本番稼働確認（2026-08-29、⑨⑩の「未確認」がこれで確認完了）**:
  - open 17:00:16 JST / promo 18:00〜18:01 JST に **外部cron（cron-job.org → `workflow_dispatch`）で投稿成功**。待機ステップが定刻ちょうどまで `sleep` して時刻も正確
  - GitHub内蔵cronは今回も約5.5時間遅延して発火（22:18 / 22:58 JST）したが、新スキップ判定が「本日分は投稿済み」を検知して **待機・投稿をスキップ（二重投稿なし）**
  - healthchecks.io も成功pingで復旧（8/28分のDOWNから「UP」通知）
  - 補足: GitHub内蔵cronは相変わらず定刻に発火しない。実運用は **外部cron（cron-job.org）が主、内蔵cronは保険** という形で回っている

## 次にやること

- `IG_ACCESS_TOKEN` の再発行（**次回失効 2026-10-28**。残り10日で自動警告が飛ぶ。手順は README §9／作業メモ）
- `cron-job.org` の GitHub PAT の有効期限（**2027-08-26**）をカレンダーに登録して更新漏れを防ぐ
- 長期休業などで `PAUSE` フラグを使う運用が実際に機能するか、次の休業時に確認
- 画像を追加・入れ替える際は9:16比率を保つこと（README §5参照）

## 未確認の受け入れ基準

`SPEC.md` §15 のうち、以下がまだ未確認（実運用の中で自然に確認できるものが多い）。

- 12: A1セルに `PAUSE` を入れると全スロットが止まる
- 7, 8: 投稿数上限の不足時・`all` モード途中失敗時の挙動
- 14, 15: CSV取得失敗時のフォールバック（実URLでの再確認）
- 18: トークン破損時の通知（BOM混入トラブルの際に間接的に確認済み。意図的な破損テストは未実施）

1〜6, 9〜11, 13, 16, 17, 19 はローカル検証・本番投稿の両方で確認済み。
起動二重化・二重投稿防止・healthchecks成功ping・投稿時刻の正確さは 2026-08-29 の本番稼働で確認済み（⑪）。
