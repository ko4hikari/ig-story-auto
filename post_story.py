#!/usr/bin/env python3
"""Instagram ストーリーズ自動投稿ツール。詳細は SPEC.md を参照。"""

import argparse
import csv
import io
import json
import os
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import requests

# Windows のコンソール(cp932等)でも日本語ログ・通知を安全に出力できるようにする
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------

JST = timezone(timedelta(hours=9))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
CLOSED_DAYS_PATH = os.path.join(BASE_DIR, "closed_days.txt")
# スロットごとの「最終投稿日」を記録するファイル。二重投稿の防止に使う。
# closed_days.txt と同様、workflow が変更を自動コミットする。
LAST_POST_PATH = os.path.join(BASE_DIR, "last_post.json")

IG_API_VERSION = os.environ.get("IG_API_VERSION") or "v23.0"
# Facebookログイン方式（ページ経由）のInstagram APIを使用する。
# エンドポイントは graph.facebook.com で、対象は "me" ではなく IG_USER_ID を明示する。
IG_BASE = f"https://graph.facebook.com/{IG_API_VERSION}"

RETRY_DELAYS = [5, 15, 45]  # 秒。指数バックオフ（最大3回リトライ = 計4回試行）
CONTAINER_WAIT_SECONDS = 5
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
WEEKDAY_JA = ["月", "火", "水", "木", "金", "土", "日"]

TYPE_OPEN_ONLY = "open_only"
TYPE_ALL = "all"
TYPE_LABELS = {
    "": TYPE_OPEN_ONLY,
    "オープンのみ停止": TYPE_OPEN_ONLY,
    "全停止": TYPE_ALL,
}

# ---------------------------------------------------------------------------
# ログ・秘匿情報マスキング
# ---------------------------------------------------------------------------

_SECRETS = []


def register_secret(value):
    """ログに出さない秘匿文字列として登録する。"""
    if value:
        _SECRETS.append(value)


def mask(text):
    """既知の秘匿文字列(アクセストークン等)を '***' に置換する。"""
    if text is None:
        return text
    text = str(text)
    for secret in _SECRETS:
        if secret:
            text = text.replace(secret, "***")
    return text


def log(msg):
    ts = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts} JST] {mask(msg)}")


def log_err(msg):
    ts = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts} JST] {mask(msg)}", file=sys.stderr)


def notify(message):
    """失敗・異常系の通知を Discord/Slack 互換Webhookに送る。

    例外メッセージ経由でアクセストークンが紛れ込む経路がありうるため、
    ローカルログだけでなく Webhook に送る内容も必ずマスクする。
    """
    safe_message = mask(message)
    log(f"NOTIFY: {safe_message}")
    webhook = os.environ.get("NOTIFY_WEBHOOK")
    if not webhook:
        log_err("NOTIFY_WEBHOOK が未設定のため通知を送信できません")
        return
    # Discord は "content"、Slack Incoming Webhook は "text" を見るので両方送る
    payload = {"content": safe_message, "text": safe_message}
    try:
        requests.post(webhook, json=payload, timeout=15)
    except requests.RequestException as e:
        log_err(f"通知の送信に失敗しました: {e}")


# ---------------------------------------------------------------------------
# 死活監視 (healthchecks.io) と 二重投稿の防止 (last_post.json)
# ---------------------------------------------------------------------------


def ping_healthcheck(suffix=""):
    """healthchecks.io に死活監視のpingを送る。

    環境変数 HEALTHCHECK_URL が未設定なら何もしない。
    suffix="" は成功ping（正常稼働の合図）、suffix="/fail" は失敗ping。
    予定時刻を過ぎてもpingが届かなければ、healthchecks.io 側が
    「投稿されていない」と判断して Discord に自動通知する。
    """
    base = (os.environ.get("HEALTHCHECK_URL") or "").strip()
    if not base:
        return
    url = base.rstrip("/") + suffix
    try:
        requests.get(url, timeout=10)
        log(f"healthcheck ping 送信: {suffix or 'success'}")
    except requests.RequestException as e:
        log_err(f"healthcheck ping の送信に失敗しました: {e}")


def _read_last_post():
    """last_post.json を読む。ファイルが無い・壊れている場合は空の辞書を返す。"""
    try:
        with open(LAST_POST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_last_post(slot_name, date_str):
    """スロットの最終投稿日（JST）を last_post.json に記録する。"""
    data = _read_last_post()
    data[slot_name] = date_str
    try:
        with open(LAST_POST_PATH, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
    except OSError as e:
        log_err(f"last_post.json の書き込みに失敗しました: {e}")


# ---------------------------------------------------------------------------
# HTTP (リトライ付き)
# ---------------------------------------------------------------------------


class RequestFailure(Exception):
    def __init__(self, status_code, body):
        self.status_code = status_code
        self.body = body
        super().__init__(f"HTTP {status_code}: {body}")


def _do_request(method, url, **kwargs):
    """最大3回リトライ（5秒→15秒→45秒）してHTTPリクエストする。

    ネットワークエラーおよび 429/5xx は再試行対象。
    それ以外の 4xx は再試行しても無駄なので即座に RequestFailure を投げる。
    """
    delays = [0] + RETRY_DELAYS
    last_exc = None
    for i, delay in enumerate(delays):
        if delay:
            log(f"retrying in {delay}s (attempt {i + 1}/{len(delays)}): {method} {url}")
            time.sleep(delay)
        try:
            resp = requests.request(method, url, timeout=30, **kwargs)
        except requests.RequestException as e:
            last_exc = e
            log_err(f"HTTP {method} {url} failed (attempt {i + 1}/{len(delays)}): {e}")
            continue
        if resp.status_code < 400:
            return resp
        if resp.status_code in (429, 500, 502, 503, 504) and i < len(delays) - 1:
            log_err(
                f"HTTP {method} {url} -> {resp.status_code} "
                f"(attempt {i + 1}/{len(delays)}), retrying"
            )
            last_exc = RequestFailure(resp.status_code, resp.text)
            continue
        raise RequestFailure(resp.status_code, resp.text)
    raise last_exc if last_exc else RequestFailure(0, "unknown error")


# ---------------------------------------------------------------------------
# config.json
# ---------------------------------------------------------------------------


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {s["name"]: s for s in data.get("slots", [])}


def get_slot(slots, name):
    if name not in slots:
        raise SystemExit(f"slot '{name}' is not defined in config.json")
    return slots[name]


# ---------------------------------------------------------------------------
# 画像
# ---------------------------------------------------------------------------


def list_slot_images(folder):
    path = os.path.join(BASE_DIR, folder)
    if not os.path.isdir(path):
        return []
    files = []
    for fn in os.listdir(path):
        if fn.startswith("_"):
            continue
        ext = os.path.splitext(fn)[1].lower()
        if ext in IMAGE_EXTENSIONS:
            files.append(fn)
    return sorted(files)


def build_image_url(folder, filename):
    base_url = (os.environ.get("IMAGE_BASE_URL") or "").rstrip("/")
    folder_part = "/".join(urllib.parse.quote(p) for p in folder.strip("/").split("/"))
    return f"{base_url}/{folder_part}/{urllib.parse.quote(filename)}"


def select_rotate_image(images, today):
    index = today.toordinal() % len(images)
    return images[index]


# ---------------------------------------------------------------------------
# 休業日 (Googleスプレッドシート / closed_days.txt キャッシュ)
# ---------------------------------------------------------------------------


class ClosedDaysUnavailable(Exception):
    pass


def _parse_sheet_date(raw):
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    # Google Sheets export may omit zero-padding (e.g. 2026/8/17)
    for sep in ("-", "/"):
        parts = raw.split(sep)
        if len(parts) == 3:
            try:
                y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
                return datetime(y, m, d).date()
            except ValueError:
                pass
    return None


def _fetch_csv_text():
    url = os.environ.get("CLOSED_DAYS_CSV_URL")
    if not url:
        raise ClosedDaysUnavailable("CLOSED_DAYS_CSV_URL is not set")
    try:
        resp = _do_request("GET", url)
    except (RequestFailure, requests.RequestException) as e:
        raise ClosedDaysUnavailable(f"CSV取得に失敗しました: {e}")
    # Google スプレッドシートのCSV公開はUTF-8。Content-Typeにcharsetが無い場合
    # requestsがISO-8859-1等を誤って推測することがあるため明示的に上書きする。
    resp.encoding = "utf-8"
    return resp.text


def _parse_csv(text):
    """CSVをパースする。戻り値: (paused, entries, warnings)

    entries: {date: (type, memo, line_no)}  line_no は data_rows 側の元CSV行番号(参考値)
    """
    paused = False
    entries = {}
    warnings = []
    reader = list(csv.reader(io.StringIO(text)))
    if not reader:
        return paused, entries, warnings

    first_row = reader[0]
    a1 = (first_row[0] if first_row else "").strip()
    if a1.upper() == "PAUSE":
        paused = True

    for line_no, row in enumerate(reader[1:], start=2):
        if not row or not row[0].strip():
            continue
        raw_date = row[0]
        raw_type = row[1].strip() if len(row) > 1 else ""
        raw_memo = row[2].strip() if len(row) > 2 else ""

        d = _parse_sheet_date(raw_date)
        if d is None:
            warnings.append(f"row {line_no}: 日付を解釈できませんでした: '{raw_date}'")
            continue
        if raw_type not in TYPE_LABELS:
            warnings.append(f"row {line_no}: 種別を解釈できませんでした: '{raw_type}'")
            continue

        type_ = TYPE_LABELS[raw_type]
        existing = entries.get(d)
        if existing is None or (existing[0] != TYPE_ALL and type_ == TYPE_ALL):
            entries[d] = (type_, raw_memo, line_no)

    return paused, entries, warnings


def _write_cache(paused, entries):
    lines = [
        "# closed_days.txt - auto-generated cache. Do not edit manually.",
        f"# updated: {datetime.now(JST).isoformat()}",
        f"PAUSE={'true' if paused else 'false'}",
    ]
    for d in sorted(entries.keys()):
        type_, memo, _ = entries[d]
        lines.append(f"{d.isoformat()},{type_},{memo}")
    with open(CLOSED_DAYS_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def _read_cache():
    if not os.path.exists(CLOSED_DAYS_PATH):
        return None
    paused = False
    entries = {}
    with open(CLOSED_DAYS_PATH, "r", encoding="utf-8") as f:
        for line_no, raw_line in enumerate(f, start=1):
            line = raw_line.rstrip("\n")
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if line.startswith("PAUSE="):
                paused = line.split("=", 1)[1].strip().lower() == "true"
                continue
            parts = line.split(",", 2)
            if len(parts) < 2:
                continue
            date_str, type_ = parts[0], parts[1]
            memo = parts[2] if len(parts) > 2 else ""
            try:
                d = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                continue
            if type_ not in (TYPE_OPEN_ONLY, TYPE_ALL):
                continue
            entries[d] = (type_, memo, line_no)
    return paused, entries


@dataclass
class ClosedDaysState:
    ok: bool
    paused: bool = False
    entries: dict = field(default_factory=dict)
    source: str = ""  # "fetched" | "cache" | "none"
    error: str = ""


def resolve_closed_days():
    """休業日情報を取得する。SPEC.md §6 のフォールバック方針に従う。

    1. 取得成功 -> closed_days.txt に書き出してそれを使う
    2. 取得失敗 -> closed_days.txt があればそれを使い、通知する
    3. 取得失敗かつキャッシュも無い -> 通知して ok=False を返す（投稿しない）
    """
    try:
        text = _fetch_csv_text()
        paused, entries, warnings = _parse_csv(text)
        for w in warnings:
            log_err(f"CSV警告: {w}")
        _write_cache(paused, entries)
        return ClosedDaysState(ok=True, paused=paused, entries=entries, source="fetched")
    except ClosedDaysUnavailable as e:
        log_err(f"休業日CSVの取得に失敗しました: {e}")
        cached = _read_cache()
        if cached is None:
            notify(
                "休業日情報の取得に失敗し、キャッシュ(closed_days.txt)も存在しないため、"
                f"投稿を中止しました。詳細: {e}"
            )
            return ClosedDaysState(ok=False, source="none", error=str(e))
        paused, entries = cached
        notify(
            "休業日CSVの取得に失敗したため、closed_days.txt のキャッシュを使用して"
            f"続行します。詳細: {e}"
        )
        return ClosedDaysState(ok=True, paused=paused, entries=entries, source="cache")


def slot_status(slot, d, state):
    """スロットがその日に投稿するかどうかを判定する。戻り値: (will_post, reason)"""
    if not state.ok:
        return False, "休業日情報取得不可"
    if state.paused:
        return False, "PAUSE"
    entry = state.entries.get(d)
    if entry:
        type_, memo, line_no = entry
        blocks = type_ == TYPE_ALL or (
            type_ == TYPE_OPEN_ONLY and slot.get("respect_closed_days", True)
        )
        if blocks:
            reason = f"closed_days.txt:{line_no}"
            if memo:
                reason += f" ({memo})"
            return False, reason
    return True, None


# ---------------------------------------------------------------------------
# Instagram API
# ---------------------------------------------------------------------------


def _ig_params(token, **extra):
    params = dict(extra)
    params["access_token"] = token
    return params


def create_media_container(token, ig_user_id, image_url):
    resp = _do_request(
        "POST",
        f"{IG_BASE}/{ig_user_id}/media",
        params=_ig_params(token, image_url=image_url, media_type="STORIES"),
    )
    return resp.json()["id"]


def publish_media(token, ig_user_id, creation_id):
    resp = _do_request(
        "POST",
        f"{IG_BASE}/{ig_user_id}/media_publish",
        params=_ig_params(token, creation_id=creation_id),
    )
    return resp.json()


def get_publishing_limit(token, ig_user_id):
    """24時間の移動窓での残投稿可能数を返す。判定不能なら None。"""
    resp = _do_request(
        "GET",
        f"{IG_BASE}/{ig_user_id}/content_publishing_limit",
        params=_ig_params(token, fields="quota_usage,config"),
    )
    data = resp.json()
    entries = data.get("data") or [{}]
    entry = entries[0]
    usage = entry.get("quota_usage")
    total = entry.get("config", {}).get("quota_total")
    if usage is None or total is None:
        return None
    return max(total - usage, 0)


def post_one_image(token, ig_user_id, image_url):
    """1枚投稿する。戻り値: (ok, status, body)"""
    try:
        creation_id = create_media_container(token, ig_user_id, image_url)
    except RequestFailure as e:
        return False, e.status_code, e.body
    except (requests.RequestException, KeyError, ValueError) as e:
        return False, None, str(e)

    time.sleep(CONTAINER_WAIT_SECONDS)

    try:
        publish_media(token, ig_user_id, creation_id)
    except RequestFailure as e:
        return False, e.status_code, e.body
    except (requests.RequestException, KeyError, ValueError) as e:
        return False, None, str(e)

    return True, 200, ""


# ---------------------------------------------------------------------------
# コマンド: --check
# ---------------------------------------------------------------------------


def cmd_check(slots):
    state = resolve_closed_days()
    today = datetime.now(JST).date()

    if not state.ok:
        print("休業日情報を取得できず、キャッシュも存在しないため予定を表示できません。")
        return 1

    for i in range(14):
        d = today + timedelta(days=i)
        wd = WEEKDAY_JA[d.weekday()]
        parts = [f"{d.isoformat()} ({wd})"]
        for name, slot in slots.items():
            will_post, reason = slot_status(slot, d, state)
            if not will_post:
                parts.append(f"{name}:休業 ← {reason}")
                continue
            images = list_slot_images(slot["folder"])
            if not images:
                parts.append(f"{name}:投稿対象なし")
                continue
            if slot["mode"] == "rotate":
                fn = select_rotate_image(images, d)
                parts.append(f"{name}:投稿 {fn}")
            else:
                parts.append(f"{name}:投稿 {len(images)}枚")
        print("  ".join(parts))
    return 0


# ---------------------------------------------------------------------------
# コマンド: --dry-run
# ---------------------------------------------------------------------------


def cmd_dry_run(slots, slot_name):
    slot = get_slot(slots, slot_name)
    state = resolve_closed_days()
    today = datetime.now(JST).date()

    if not state.ok:
        print(f"[{slot_name}] 投稿しない: 理由=休業日情報が取得できずキャッシュも無いため")
        return 1

    will_post, reason = slot_status(slot, today, state)
    if not will_post:
        print(f"[{slot_name}] 投稿しない: 理由={reason}")
        return 0

    images = list_slot_images(slot["folder"])
    if not images:
        print(f"[{slot_name}] 投稿しない: 理由=対象画像が0枚")
        return 1

    print(f"[{slot_name}] 投稿する")
    if slot["mode"] == "rotate":
        fn = select_rotate_image(images, today)
        print(f"  {fn} -> {build_image_url(slot['folder'], fn)}")
    else:
        for fn in images:
            print(f"  {fn} -> {build_image_url(slot['folder'], fn)}")
    return 0


# ---------------------------------------------------------------------------
# コマンド: 実投稿
# ---------------------------------------------------------------------------


def cmd_post(slots, slot_name):
    """実投稿のエントリポイント。処理結果に応じて healthchecks.io へpingを送る。

    戻り値 0（投稿成功・または休業などで意図的に投稿しなかった）→ 成功ping
    戻り値 1（異常で投稿できなかった）→ 失敗ping
    """
    rc = _run_post(slots, slot_name)
    ping_healthcheck("" if rc == 0 else "/fail")
    return rc


def _run_post(slots, slot_name):
    slot = get_slot(slots, slot_name)
    token = os.environ.get("IG_ACCESS_TOKEN", "")
    ig_user_id = os.environ.get("IG_USER_ID", "")
    if not token:
        notify(f"[{slot_name}] IG_ACCESS_TOKEN が未設定です")
        return 1
    if not ig_user_id:
        notify(f"[{slot_name}] IG_USER_ID が未設定です")
        return 1

    state = resolve_closed_days()
    if not state.ok:
        return 1  # resolve_closed_days 内で通知済み

    today = datetime.now(JST).date()
    today_str = today.isoformat()

    # 二重投稿の防止: 外部cron(cron-job.org)とGitHubのcronが両方起動しても、
    # 同じ日に同じスロットを投稿するのは1回だけにする。
    if _read_last_post().get(slot_name) == today_str:
        log(f"[{slot_name}] 本日分（{today_str}）は投稿済みのためスキップします")
        return 0

    will_post, reason = slot_status(slot, today, state)
    if not will_post:
        log(f"[{slot_name}] 本日は休業のため投稿しません ({reason})")
        return 0

    images = list_slot_images(slot["folder"])
    if not images:
        notify(f"[{slot_name}] 対象画像が0枚のため投稿できません（フォルダ: {slot['folder']}）")
        return 1

    if slot["mode"] == "rotate":
        rc = _post_rotate(slot_name, slot, images, today, token, ig_user_id)
    else:
        rc = _post_all(slot_name, slot, images, token, ig_user_id)

    # 完全に成功したときだけ「投稿済み」として記録する。
    # 一部失敗のときは記録せず、後続の起動でのリトライ機会を残す。
    if rc == 0:
        _write_last_post(slot_name, today_str)
    return rc


def _post_rotate(slot_name, slot, images, today, token, ig_user_id):
    fn = select_rotate_image(images, today)
    url = build_image_url(slot["folder"], fn)
    ok, status, body = post_one_image(token, ig_user_id, url)
    if not ok:
        notify(f"[{slot_name}] 投稿失敗: {fn} status={status} body={body}")
        return 1
    log(f"[{slot_name}] 投稿成功: {fn}")
    return 0


def _post_all(slot_name, slot, images, token, ig_user_id):
    interval = slot.get("interval_seconds", 30)

    try:
        remaining = get_publishing_limit(token, ig_user_id)
    except RequestFailure as e:
        notify(
            f"[{slot_name}] 投稿数上限の取得に失敗したため中止しました: "
            f"status={e.status_code} body={e.body}"
        )
        return 1
    except requests.RequestException as e:
        notify(f"[{slot_name}] 投稿数上限の取得に失敗したため中止しました: {e}")
        return 1

    if remaining is None:
        notify(f"[{slot_name}] 投稿数上限を判定できなかったため中止しました")
        return 1
    if remaining == 0:
        notify(f"[{slot_name}] 投稿数上限に達しているため投稿できません（画像 {len(images)} 枚）")
        return 1

    to_post = images[:remaining]
    skipped = images[remaining:]

    successes = []
    failures = []  # (filename, status, body)
    for i, fn in enumerate(to_post):
        url = build_image_url(slot["folder"], fn)
        ok, status, body = post_one_image(token, ig_user_id, url)
        if ok:
            successes.append(fn)
            log(f"[{slot_name}] 投稿成功: {fn}")
        else:
            failures.append((fn, status, body))
            log_err(f"[{slot_name}] 投稿失敗: {fn} status={status}")
        if i < len(to_post) - 1:
            time.sleep(interval)

    if failures or skipped:
        lines = [f"[{slot_name}] all投稿完了: {len(successes)}/{len(images)} 枚成功"]
        if failures:
            lines.append("失敗:")
            for fn, status, body in failures:
                lines.append(f"  - {fn} status={status} body={body}")
        if skipped:
            lines.append(f"上限超過によりスキップ: {', '.join(skipped)}")
        notify("\n".join(lines))
        return 1

    log(f"[{slot_name}] all投稿完了: {len(successes)}/{len(images)} 枚成功")
    return 0


# ---------------------------------------------------------------------------
# コマンド: --refresh-token
# ---------------------------------------------------------------------------


def cmd_refresh_token():
    """アクセストークンの有効性を確認する。

    Facebookログイン方式で発行した長期ページアクセストークンは、
    ユーザーがパスワード変更やアプリ連携解除をしない限り実質無期限で失効しない
    （Instagramログイン方式のような60日ごとの自動リフレッシュAPIが存在しない）。
    そのため、ここでは定期的に有効性だけを確認し、無効化されていた場合に
    Graph APIエクスプローラーからの手動再取得を促す通知を送る。
    """
    token = os.environ.get("IG_ACCESS_TOKEN", "")
    if not token:
        notify("トークン確認失敗: IG_ACCESS_TOKEN が未設定です")
        return 1

    try:
        resp = _do_request(
            "GET",
            "https://graph.facebook.com/me",
            params={"access_token": token, "fields": "id,name"},
        )
        data = resp.json()
    except RequestFailure as e:
        notify(
            "アクセストークンが無効になっている可能性があります。Graph APIエクスプローラーから"
            f"再取得し、IG_ACCESS_TOKEN を更新してください。status={e.status_code} body={e.body}"
        )
        return 1
    except (requests.RequestException, KeyError, ValueError) as e:
        notify(f"アクセストークンの有効性確認に失敗しました: {e}")
        return 1

    log(f"アクセストークンは有効です（対象: {data.get('name', 'unknown')}）")
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Instagram ストーリーズ自動投稿ツール")
    parser.add_argument("--slot", help="対象スロット名（config.json で定義）")
    parser.add_argument("--dry-run", action="store_true", help="投稿せずに判定内容のみ表示する")
    parser.add_argument("--check", action="store_true", help="今後14日間の予定を全スロット表示する")
    parser.add_argument("--refresh-token", action="store_true", help="アクセストークンをリフレッシュする")
    args = parser.parse_args()

    # ログにトークン等が出力されないよう、最初に秘匿情報として登録しておく
    register_secret(os.environ.get("IG_ACCESS_TOKEN"))
    register_secret(os.environ.get("GH_PAT"))
    register_secret(os.environ.get("NOTIFY_WEBHOOK"))
    register_secret(os.environ.get("HEALTHCHECK_URL"))

    if args.refresh_token:
        return cmd_refresh_token()

    slots = load_config()

    if args.check:
        return cmd_check(slots)

    if not args.slot:
        parser.error("--slot is required unless --check or --refresh-token is given")

    if args.dry_run:
        return cmd_dry_run(slots, args.slot)

    return cmd_post(slots, args.slot)


if __name__ == "__main__":
    sys.exit(main())
