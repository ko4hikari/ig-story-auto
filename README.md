# Instagram ストーリーズ自動投稿ツール

店舗の Instagram アカウントに、1日複数の時間帯（スロット）でストーリーズを自動投稿する GitHub Actions ベースのツール。
詳細な仕様は [`SPEC.md`](./SPEC.md) を参照。依存ライブラリは `requests` のみ。

```
repo/
├── .github/workflows/
│   ├── slot-open.yml        # open スロット（毎日17:00 JST 起動）
│   ├── slot-promo.yml       # promo スロット（毎日18:00 JST 起動）
│   └── refresh-token.yml    # 週1回、アクセストークンの有効性を確認（自動更新はしない）
├── assets/
│   ├── open/                # open スロットの画像（本番画像7枚）
│   └── promo/                # promo スロットの画像（本番画像3枚）
├── config.json               # スロット定義
├── closed_days.txt           # 休業日キャッシュ（自動更新・手で編集しない）
├── post_story.py
└── SPEC.md
```

---

## 1. 事前準備（Instagram / Meta 側）

**採用方式: Instagram API with Facebook Login**（`graph.facebook.com`、対象Instagramアカウントに**連携済みのFacebookページ**が必要）。
「Instagram Login」方式（`graph.instagram.com`）は、開発者ロールやテスター招待周りの不具合が多く安定しなかったため不採用。

1. Instagram アカウントを **プロアカウント（ビジネス）** に切り替え、**Facebookページと連携**しておく（連携済みページは他用途（例: Meta広告）と共用でよい。**そのページを解除・削除しないこと**）
2. https://developers.facebook.com で開発者登録し、アプリを新規作成する。プロダクトに **Instagram** と **Facebookログイン** を追加する
3. [Meta Business Suite](https://business.facebook.com/latest/settings/system_users) の「システムユーザー」で、投稿専用の**システムユーザー**（人間のアカウントではないAPI専用アカウント）を作成する
4. アプリの「ロール」設定で、そのシステムユーザーを**テスター**として追加する（数値IDで検索すること。ユーザー名検索は失敗しやすい）
5. システムユーザーの「割り当てられたアセット」で、対象のFacebookページを割り当てる（権限は投稿に必要な「コンテンツ」があればよい）
6. システムユーザーの詳細画面で「トークンを生成」→ 対象アプリを選択 → 有効期限「60日間」を選択 → 権限はデフォルトのまま生成
7. 発行されたトークンは**画面に表示された直後にコピーし**、後述の `IG_ACCESS_TOKEN` シークレットに設定する（App Secretは一切不要な方式）
8. 対象のInstagramビジネスアカウントID（`IG_USER_ID`）は [グラフAPIエクスプローラー](https://developers.facebook.com/tools/explorer/) で `GET /me/accounts` → 該当ページの `GET /{page-id}?fields=instagram_business_account` から確認できる

App Review は不要。自分（自社）が所有・管理するページ・アカウントのみを対象とする場合は Standard Access で足りる。

APIバージョンは `post_story.py` 冒頭の `IG_API_VERSION`（デフォルト `v23.0`）で管理している。Meta 公式ドキュメントで最新の安定版を確認し、古くなっていたら値を更新するか、環境変数 `IG_API_VERSION` で上書きすること。

---

## 2. 事前準備（Googleスプレッドシート = 休業日入力窓口）

スタッフ全員がGitHubを触るのは非現実的なため、休業日の入力窓口はGoogleスプレッドシートにする。

1. 新しいスプレッドシートを作成し、以下の形式で列を用意する（1行目はヘッダー、読み飛ばされる）

   | A: 日付 | B: 種別 | C: メモ |
   |---|---|---|
   | 2026-08-17 | オープンのみ停止 | |
   | 2026-08-20 | 全停止 | 台風 |

2. **B列にプルダウン（データの入力規則）を設定する。** 手入力させると表記ゆれで事故るため。
   - `データ` → `データの入力規則` → リストを直接指定 → `オープンのみ停止`, `全停止` の2つを登録
   - B列が空欄の場合は `オープンのみ停止` として扱われる
3. `ファイル` → `共有` → `ウェブに公開` から、対象シートを **CSV形式** で公開する（認証不要でGETできるURLが発行される）
4. 発行されたURLを `CLOSED_DAYS_CSV_URL` シークレットに設定する
5. **緊急停止**: シートの **A1セル** に `PAUSE` と入力すると、日付に関係なく全スロットが停止する。長期休業や不具合時の緊急ブレーキとして使う

日付は `2026-08-17` / `2026/08/17` / `2026/8/17` のいずれの表記でも解釈される。解釈できない行は警告ログを出してスキップされ、処理全体は止まらない。

CSVは日付情報のみなので公開しても実害は少ないが、URLを知っていれば誰でも閲覧できる点は把握しておくこと。

---

## 3. GitHub Secrets

リポジトリの `Settings` → `Secrets and variables` → `Actions` から以下を設定する。

| 名前 | 内容 |
|---|---|
| `IG_ACCESS_TOKEN` | システムユーザーの長期ページアクセストークン（60日間有効。§1参照） |
| `IG_USER_ID` | 投稿対象のInstagramビジネスアカウントID（数値） |
| `IMAGE_BASE_URL` | raw URL のベース。末尾スラッシュなし。例: `https://raw.githubusercontent.com/{user}/{repo}/main` |
| `NOTIFY_WEBHOOK` | 失敗通知先（Discord または Slack の Incoming Webhook URL） |
| `CLOSED_DAYS_CSV_URL` | 休業日シートの公開CSV URL |

CLIから設定する場合:

```bash
gh secret set IG_ACCESS_TOKEN --body "取得したトークン"
gh secret set IG_USER_ID --body "1784xxxxxxxxxxxx"
gh secret set IMAGE_BASE_URL --body "https://raw.githubusercontent.com/USER/REPO/main"
gh secret set NOTIFY_WEBHOOK --body "https://discord.com/api/webhooks/..."
gh secret set CLOSED_DAYS_CSV_URL --body "https://docs.google.com/.../pub?output=csv"
```

**Windows PowerShellで設定する場合は `--body` を使うこと。** `Get-Clipboard | gh secret set NAME` のようにパイプで渡すと、PowerShellの既定エンコーディングにより値の先頭に見えないBOM文字が混入し、トークンやURLとして正しく認識されなくなる（実際にこの事故が起きて `IG_ACCESS_TOKEN` と `NOTIFY_WEBHOOK` が壊れたことがある）。`gh secret set NAME --body $value` の形式なら安全。

**画像を公開raw URLで配信するため、リポジトリは public にする。** private リポジトリのraw URLは認証が必要で、Instagram側から取得できない。private にしたい場合は画像だけ別の公開ストレージ（S3など）に置き、`IMAGE_BASE_URL` をそちらに向けること。

---

## 4. config.json（スロット定義）

```json
{
  "slots": [
    {
      "name": "open",
      "folder": "assets/open",
      "mode": "rotate",
      "time_jst": "17:00",
      "respect_closed_days": true
    },
    {
      "name": "promo",
      "folder": "assets/promo",
      "mode": "all",
      "time_jst": "18:00",
      "interval_seconds": 30,
      "respect_closed_days": false
    }
  ]
}
```

| キー | 説明 |
|---|---|
| `name` | スロット識別子。CLI (`--slot`) と workflow から参照する |
| `folder` | 画像フォルダのパス（リポジトリルートからの相対パス） |
| `mode` | `rotate`（日替わりで1枚） または `all`（フォルダ内全部） |
| `time_jst` | 投稿時刻（JST）。**ドキュメント用。** 実際の起動時刻は各 workflow の `cron` が決めるので、変更する場合は両方直すこと |
| `interval_seconds` | `all` モード時の投稿間隔。省略時は30秒 |
| `respect_closed_days` | `true` なら休業日に投稿しない。`false` なら休業日も投稿する。省略時は `true` |

### スロットを追加する（3つ目の例: `night`）

コードの変更は不要。以下の3ステップだけで動く。

1. `assets/night/` フォルダを作り、画像を入れる
2. `config.json` の `slots` 配列に追記する

   ```json
   {
     "name": "night",
     "folder": "assets/night",
     "mode": "rotate",
     "time_jst": "22:00",
     "respect_closed_days": true
   }
   ```

3. `.github/workflows/slot-open.yml` をコピーして `.github/workflows/slot-night.yml` を作り、以下を書き換える（§10参照）
   - `cron`: 目標時刻より20〜25分早い`:00`以外の分にする（22:00 JST目標なら例えば `35 12 * * *` = 21:35 JST）
   - 「Wait until」ステップの `TARGET_EPOCH` に渡す時刻を目標時刻のUTC表記にする（22:00 JST → `13:00:00`）
   - `--slot night`

---

## 5. 画像の追加・削除（スマホから完結）

- 各スロットのフォルダ（例: `assets/open/`）に画像を置くだけ。枚数は自由で、コード変更は不要
- 対応拡張子: `.jpg` `.jpeg` `.png`。推奨サイズ 1080×1920（9:16）、8MB以下
- ファイル名は半角英数字にする（日本語やスペースを含む場合はURLエンコードして扱われるが、事故防止のため半角推奨）
- ファイル名が `_` で始まる画像は対象外になる。一時的に外したい時は削除せずリネームすればよい
- `rotate` モードは「その日の日付から一意に決まるインデックス」で1枚選ぶため状態ファイル不要。画像を1枚足すだけで翌日から自動でローテーションに入る
- `all` モードはファイル名の**昇順**に全部投稿する。並び順を制御したい場合はファイル名の先頭（`01_`, `02_` など）で調整する

GitHubモバイルアプリ、または `github.com` をスマホのブラウザで開き、該当フォルダで `Add file → Upload files` すれば操作は完結する。

---

## 6. 動作確認

### `--check`: 今後14日間の投稿予定を一覧表示

```bash
python post_story.py --check
```

```
2026-08-16 (日)  open:投稿 02.jpg  promo:投稿 2枚
2026-08-17 (月)  open:休業 ← closed_days.txt:5  promo:投稿 2枚
2026-08-20 (木)  open:休業 ← closed_days.txt:6 (台風)  promo:休業 ← closed_days.txt:6 (台風)
```

休業日でも `respect_closed_days: false` のスロット（デフォルトの `promo`）は投稿予定として表示される。休業行には `closed_days.txt` の何行目が効いているかが必ず表示されるので、シートの書き間違いにその場で気づける。

### `--dry-run`: 実際には投稿せず判定内容だけ表示

```bash
python post_story.py --slot open --dry-run
python post_story.py --slot promo --dry-run
```

投稿する/しないと、その理由（`PAUSE` / `closed_days.txt:N`）、投稿予定の画像ファイル名とURLが出力される。

これらのコマンドは Instagram API を一切呼ばないため、`IG_ACCESS_TOKEN` が無くても（`CLOSED_DAYS_CSV_URL` と、URL表示のためにできれば `IMAGE_BASE_URL` があれば）ローカルで検証できる。

```bash
export CLOSED_DAYS_CSV_URL="https://docs.google.com/.../pub?output=csv"
export IMAGE_BASE_URL="https://raw.githubusercontent.com/USER/REPO/main"
python post_story.py --check
```

### 実投稿

```bash
python post_story.py --slot open
python post_story.py --slot promo
```

`IG_ACCESS_TOKEN` / `IMAGE_BASE_URL` / `NOTIFY_WEBHOOK` / `CLOSED_DAYS_CSV_URL` の環境変数が必要。通常は GitHub Actions の workflow が Secrets から注入して実行する。

### 手動実行（GitHub Actions）

各 workflow には `workflow_dispatch` が入っているため、GitHub の `Actions` タブから手動実行できる（スマホのブラウザからも操作可能）。

---

## 7. 投稿処理の仕組み

- 採用API: **Instagram API with Facebook Login**（`graph.facebook.com`、連携済みFacebookページ経由。対象は `me` ではなく `IG_USER_ID` を明示する）
- コンテナ作成 (`POST /{IG_USER_ID}/media`) → **5秒待機** → 公開 (`POST /{IG_USER_ID}/media_publish`) の2ステップ
- `all` モードは投稿前に `GET /{IG_USER_ID}/content_publishing_limit`（`fields=quota_usage,config` 指定必須。省略するとAPIが `config` を返さず判定不能になる）で24時間の残投稿可能数を確認する
  - 残量 ≧ 投稿予定枚数 → そのまま実行
  - 残量 < 投稿予定枚数 → 入る分だけ投稿し、残りはスキップして通知
  - 残量 0 → 投稿せず通知して終了
  - 上限は**カレンダー日ではなく24時間の移動窓**（値そのものはハードコードしていない）
- API呼び出しは最大3回リトライ、指数バックオフ（5秒→15秒→45秒）
- `all` モードは途中で1枚失敗しても止めずに残りを続行し、全件終了後にまとめて通知して `exit code 1` で終了する
- 通知には「スロット名」「何枚中何枚成功したか」「失敗したファイル名」「HTTPステータス」「レスポンスbody」を含める
- ログ・通知にアクセストークンは一切出力されない（`post_story.py` 内でマスキング処理を行っている）

---

## 8. 休業日判定のフォールバック

```
[スタッフ] → Googleスプレッドシート → [毎回の実行で取得] → closed_days.txt に保存 → 判定
```

1. **取得成功** → 内容を `closed_days.txt` に書き出す。workflow が差分を検知して自動コミットする（これがキャッシュ兼変更履歴になる）
2. **取得失敗**（ネットワーク断・シート削除・権限変更など） → `closed_days.txt` の前回内容を使って続行し、同時に通知を飛ばす
3. **取得失敗かつ `closed_days.txt` も無い** → 投稿せずに終了し、通知を飛ばす

3番の判断理由: **休業日に「本日OPEN」を誤って出す方が、営業日に投稿しそこねるより損害が大きい。** 情報が無い時は投稿しない側に倒す設計にしている。

`closed_days.txt` は以下のような自動生成フォーマット。手で編集しないこと。

```
# closed_days.txt - auto-generated cache. Do not edit manually.
# updated: 2026-08-16T12:00:00+09:00
PAUSE=false
2026-08-17,open_only,
2026-08-20,all,台風
```

---

## 9. アクセストークンの有効性チェック

Facebookログイン方式のシステムユーザートークンには、Instagram Login方式のような「60日ごとに自動延長するAPI」が存在しない。パスワード変更やアプリ連携解除をしない限り実質無期限で失効しないため、`refresh-token.yml` は**自動更新ではなく有効性チェックのみ**を行う。

- `refresh-token.yml` が週1回、`python post_story.py --refresh-token` を実行する
  - `GET https://graph.facebook.com/me` にトークンを渡し、正常応答するか確認するだけ（書き換えは行わない）
- トークンが無効化されていた場合は通知が飛ぶので、[Meta Business Suiteのシステムユーザーページ](https://business.facebook.com/latest/settings/system_users)から**新しいトークンを再発行**し、`IG_ACCESS_TOKEN` を手動で更新する（§1の手順6〜7と同じ）
- 60日の有効期限が近づいても自動通知は来ないため、カレンダー等で更新時期をリマインドしておくことを推奨する

---

## 10. タイムゾーンと実行タイミング

- GitHub Actions の cron は UTC。「今日」の判定は必ず JST (`Asia/Tokyo`) で行う（`datetime.now()` をそのまま使わない設計にしている）
- **毎時ちょうど（`:00`）は GitHub Actions 全体で混雑し、scheduled workflow が数分〜30分程度遅延することがある**（実際に発生した）。対策として、各 workflow は次の2段構えにしている
  1. cron のトリガー自体は目標時刻より20〜25分早い、かつ`:00`を避けた分（例: `35 7 * * *` = 16:35 JST）に設定し、混雑を避ける
  2. 起動後、「Wait until 〜」ステップで `date`/`sleep` を使い、UTCの目標時刻（例: 08:00 UTC = 17:00 JST）ちょうどまで待機してから投稿する
  - この仕組みにより、cronの起動自体が多少遅れても、投稿時刻はほぼ正確に揃う（起動遅延が20分超のバッファを超えた場合のみズレが残る）
  - 新しいスロットを追加する際も、cronは目標時刻の20分以上前・`:00`以外の分に設定し、同様の待機ステップを入れること
  - 対応表: 17:00 JST → cron `35 7 * * *` + 待機目標 `08:00:00` UTC / 18:00 JST → cron `38 8 * * *` + 待機目標 `09:00:00` UTC
- workflow はスロットごとに1ファイル（`slot-open.yml`, `slot-promo.yml`, ...）。まとめず分けているのは事故を防ぐため。各ファイルに `workflow_dispatch` を入れて手動実行できるようにしている

---

## 11. やらないこと（意図的に対象外）

- 画像の動的生成（テキスト差し込みなど）
- メンション・リンク・投票などのステッカー（Instagram API が非対応）
- フィード投稿の引用リポスト（API にエンドポイントが存在しない）
- 投稿結果のインサイト取得

---

## 12. 受け入れ基準チェックリスト

| # | 基準 | 確認方法 |
|---|---|---|
| 1 | `--check` が14日分を全スロット・休業理由つきで表示する | `python post_story.py --check` |
| 2 | `--dry-run` が休業日／営業日で正しく判定を出す | `python post_story.py --slot open --dry-run` |
| 3 | `config.json` にスロットを1つ足すだけで3スロット目が動く | 本README §4「スロットを追加する」参照 |
| 4 | `rotate` フォルダに画像を1枚追加すると自動でローテーションに入る | `assets/open/` に画像追加 → `--check` |
| 5 | `all` フォルダに画像を1枚追加すると投稿枚数が1枚増える | `assets/promo/` に画像追加 → `--check` |
| 6 | `all` はファイル名昇順どおりに投稿される | `list_slot_images()` が `sorted()` を使用 |
| 7 | 上限不足時、入る分だけ投稿して通知 | `_post_all()` の `remaining < len(images)` 分岐 |
| 8 | `all` 途中失敗でも残りを継続し、失敗分を通知 | `_post_all()` はループを止めない設計 |
| 9 | 対象フォルダが空ならエラー通知 | `cmd_post()` の空フォルダチェック |
| 10 | シートに `オープンのみ停止` を足すと open のみ停止、promo は投稿される | `slot_status()` の `respect_closed_days` 判定 |
| 11 | シートに `全停止` を足すと両方停止する | `slot_status()` の `TYPE_ALL` 判定 |
| 12 | A1に `PAUSE` を入れると全スロット停止 | `_parse_csv()` の A1 判定 |
| 13 | 実行後、シート内容が `closed_days.txt` にコミットされる | 各 workflow の `Commit closed_days.txt if changed` ステップ |
| 14 | CSV取得失敗時、キャッシュで動作し通知が飛ぶ | `CLOSED_DAYS_CSV_URL` を無効な値にして実行 |
| 15 | CSV取得失敗かつキャッシュ不在なら投稿せず通知 | `closed_days.txt` を削除して実行 |
| 16 | `2026/8/17` 形式が正しく解釈される | `_parse_sheet_date()` |
| 17 | 壊れた行があっても処理は止まらず警告のみ | `_parse_csv()` の try/except + warnings |
| 18 | トークンを壊すと通知が飛ぶ | `IG_ACCESS_TOKEN` を不正な値にして実行 |
| 19 | ログにトークンが一切現れない | `mask()` によるマスキング（`register_secret()`） |

---

## 13. トラブルシューティング

- **`--check` / `--dry-run` で `CLOSED_DAYS_CSV_URL is not set` と出る**: 環境変数（またはSecrets）を設定しているか確認する
- **投稿が失敗し続ける**: 通知に含まれる HTTPステータスとレスポンスbodyを確認する。`190`（`Cannot parse access token` 等）はトークン失効・書式破損の可能性が高い。PowerShellでパイプ経由で `gh secret set` した場合はBOM混入を疑う（§3参照）。§1の手順で新しいトークンを再発行する
- **60日後に投稿が止まった**: `IG_ACCESS_TOKEN` の期限切れが濃厚。§1の手順6〜7で新しいトークンを再発行し、`gh secret set IG_ACCESS_TOKEN --body "..."` で更新する
- **投稿画像の左右（または上下）が切れる**: Instagramストーリーズの表示枠（9:16）と画像の比率が合っていない。1080×1920に、はみ出す方向をぼかし背景で埋めた画像に差し替える
- **休業日が反映されない**: シートの「ウェブに公開」設定が解除されていないか、B列の値が `オープンのみ停止` / `全停止` の表記と完全一致しているか確認する
