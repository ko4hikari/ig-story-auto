# Instagram ストーリーズ自動投稿ツール

店舗の Instagram アカウントに、1日複数の時間帯（スロット）でストーリーズを自動投稿する GitHub Actions ベースのツール。
詳細な仕様は [`SPEC.md`](./SPEC.md) を参照。依存ライブラリは `requests` のみ。

```
repo/
├── .github/workflows/
│   ├── slot-open.yml        # open スロット（毎日18:00 JST 起動）
│   ├── slot-promo.yml       # promo スロット（毎日12:00 JST 起動）
│   └── refresh-token.yml    # 週1回、アクセストークンをリフレッシュ
├── assets/
│   ├── open/                # open スロットの画像（サンプルを2枚同梱）
│   └── promo/                # promo スロットの画像（サンプルを2枚同梱）
├── config.json               # スロット定義
├── closed_days.txt           # 休業日キャッシュ（自動更新・手で編集しない）
├── post_story.py
└── SPEC.md
```

同梱の `assets/open/*.jpg`, `assets/promo/*.jpg` はダミー（1x1ピクセル）です。実運用前に本物の画像に差し替えてください。

---

## 1. 事前準備（Instagram / Meta 側）

1. Instagram アカウントを **プロアカウント（ビジネス）** に切り替える
2. https://developers.facebook.com で開発者登録する
3. アプリを新規作成し、プロダクトに **Instagram** を追加。ログイン方式は **Instagram Business Login** を選ぶ
4. スコープに `instagram_business_basic` / `instagram_business_content_publish` を設定する
5. 自分のアカウントを連携し、短期トークンを取得 → 長期トークン（60日）に交換する
6. App Review は不要。自分が所有・管理するアカウントのみを対象とする場合は Standard Access で足りる

取得した長期トークンは後述の `IG_ACCESS_TOKEN` シークレットに設定する。

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
| `IG_ACCESS_TOKEN` | 長期アクセストークン（60日で失効） |
| `IMAGE_BASE_URL` | raw URL のベース。末尾スラッシュなし。例: `https://raw.githubusercontent.com/{user}/{repo}/main` |
| `GH_PAT` | Secrets 更新用の Personal Access Token（`repo` スコープ、`refresh-token.yml` が使用） |
| `NOTIFY_WEBHOOK` | 失敗通知先（Discord または Slack の Incoming Webhook URL） |
| `CLOSED_DAYS_CSV_URL` | 休業日シートの公開CSV URL |

CLIから設定する場合:

```bash
gh secret set IG_ACCESS_TOKEN
gh secret set IMAGE_BASE_URL --body "https://raw.githubusercontent.com/USER/REPO/main"
gh secret set GH_PAT
gh secret set NOTIFY_WEBHOOK
gh secret set CLOSED_DAYS_CSV_URL
```

`GH_PAT` は https://github.com/settings/tokens で `repo` スコープを持つ Personal Access Token を発行して設定する（`refresh-token.yml` 内で `gh secret set IG_ACCESS_TOKEN` を実行するために必要）。

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
      "time_jst": "18:00",
      "respect_closed_days": true
    },
    {
      "name": "promo",
      "folder": "assets/promo",
      "mode": "all",
      "time_jst": "12:00",
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

3. `.github/workflows/slot-open.yml` をコピーして `.github/workflows/slot-night.yml` を作り、`cron`（22:00 JST → `0 13 * * *`）と `--slot night` の2箇所だけ書き換える

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

- 採用API: **Instagram API with Instagram Login**（`graph.instagram.com`、Facebookページ連携不要）
- コンテナ作成 (`POST /me/media`) → **5秒待機** → 公開 (`POST /me/media_publish`) の2ステップ
- `all` モードは投稿前に `GET /me/content_publishing_limit` で24時間の残投稿可能数を確認する
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

## 9. アクセストークンのリフレッシュ

- 長期トークンの有効期限は60日
- `refresh-token.yml` が週1回、`python post_story.py --refresh-token` を実行する
  1. `GET https://graph.instagram.com/refresh_access_token` で新しいトークンを取得
  2. `gh secret set IG_ACCESS_TOKEN` で GitHub Secrets に書き戻す（`GH_PAT` を使って認証）
- 書き戻しに失敗すると必ず通知される（無言で失敗すると60日後に全部止まるため）
- トークンは最低1回使われていないとリフレッシュできない。長期休業明けは要注意

---

## 10. タイムゾーンと実行タイミング

- GitHub Actions の cron は UTC。「今日」の判定は必ず JST (`Asia/Tokyo`) で行う（`datetime.now()` をそのまま使わない設計にしている）
- 例: 18:00 JST → `0 9 * * *` / 12:00 JST → `0 3 * * *` / 22:00 JST → `0 13 * * *`
- GitHub Actions の scheduled workflow は混雑時に数分〜15分程度遅延することがある。分単位の正確さが要る場合は cron を早めに設定するか、遅延を許容すること
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
- **投稿が失敗し続ける**: 通知に含まれる HTTPステータスとレスポンスbodyを確認する。`190` はトークン失効・スコープ不足の可能性が高い
- **60日後に投稿が止まった**: `refresh-token.yml` の実行履歴と通知を確認する。`GH_PAT` の期限切れ・スコープ不足が典型的な原因
- **休業日が反映されない**: シートの「ウェブに公開」設定が解除されていないか、B列の値が `オープンのみ停止` / `全停止` の表記と完全一致しているか確認する
