"""In-app notifications, phone push (Firebase Cloud Messaging) and team chat."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Iterable, Optional

import httpx

from . import database

log = logging.getLogger("uvicorn.error")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- schema
def init_tables() -> None:
    with database.get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL DEFAULT '',
                link TEXT,
                dedupe_key TEXT,
                created_at TEXT NOT NULL,
                read_at TEXT
            )
        """)
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_notifications_dedupe ON notifications(user_id, dedupe_key) WHERE dedupe_key IS NOT NULL")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, id DESC)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS push_devices (
                token TEXT PRIMARY KEY,
                user_id BIGINT NOT NULL,
                platform TEXT NOT NULL DEFAULT 'android',
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_push_devices_user ON push_devices(user_id)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS notification_runs (
                kind TEXT NOT NULL,
                run_date TEXT NOT NULL,
                started_at TEXT NOT NULL,
                PRIMARY KEY (kind, run_date)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_threads (
                id BIGSERIAL PRIMARY KEY,
                kind TEXT NOT NULL,
                title TEXT,
                group_key TEXT UNIQUE,
                direct_key TEXT UNIQUE,
                created_at TEXT NOT NULL,
                last_message_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_members (
                thread_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                last_read_id BIGINT NOT NULL DEFAULT 0,
                joined_at TEXT NOT NULL,
                PRIMARY KEY (thread_id, user_id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_members_user ON chat_members(user_id)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id BIGSERIAL PRIMARY KEY,
                thread_id BIGINT NOT NULL,
                sender_id BIGINT NOT NULL,
                sender_name TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'text',
                body TEXT NOT NULL DEFAULT '',
                retailer_code TEXT,
                retailer_name TEXT,
                photo BYTEA,
                photo_mime TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_thread ON chat_messages(thread_id, id)")


# ---------------------------------------------------------------- users
def user_by_username(username: str) -> Optional[dict]:
    if not username:
        return None
    with database.get_conn() as conn:
        row = conn.execute(
            "SELECT id, name, role, tl, ss, rds, kam, active FROM users WHERE LOWER(username) = LOWER(%s) AND active = TRUE",
            (username.strip(),),
        ).fetchone()
        return dict(row) if row else None


def active_users(roles: Iterable[str] = ("TL", "SS", "RDS", "KAM")) -> list[dict]:
    with database.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, role, tl, ss, rds, kam FROM users WHERE active = TRUE AND role = ANY(%s) ORDER BY name",
            (list(roles),),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------- notifications
def add_notification(user_id: int, kind: str, title: str, body: str = "", link: Optional[str] = None,
                     dedupe_key: Optional[str] = None, push: bool = True) -> Optional[dict]:
    """Store a notification (skipping duplicates by dedupe_key) and push it to the user's phones."""
    with database.get_conn() as conn:
        row = conn.execute(
            """
            INSERT INTO notifications (user_id, kind, title, body, link, dedupe_key, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (user_id, dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING
            RETURNING id, user_id, kind, title, body, link, created_at, read_at
            """,
            (user_id, kind, title, body, link, dedupe_key, _now()),
        ).fetchone()
    if row and push:
        send_push_async([user_id], title, body, link or "#/notifications", tag=kind)
    return dict(row) if row else None


def list_notifications(user_id: int, limit: int = 50) -> list[dict]:
    with database.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, kind, title, body, link, created_at, read_at FROM notifications WHERE user_id = %s ORDER BY id DESC LIMIT %s",
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def unread_count(user_id: int) -> int:
    with database.get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM notifications WHERE user_id = %s AND read_at IS NULL", (user_id,)).fetchone()
        return int(row["n"])


def mark_notifications_read(user_id: int, ids: Optional[list] = None) -> int:
    with database.get_conn() as conn:
        if ids:
            cur = conn.execute("UPDATE notifications SET read_at = %s WHERE user_id = %s AND read_at IS NULL AND id = ANY(%s)",
                               (_now(), user_id, list(ids)))
        else:
            cur = conn.execute("UPDATE notifications SET read_at = %s WHERE user_id = %s AND read_at IS NULL", (_now(), user_id))
        return cur.rowcount or 0


def claim_run(kind: str, run_date: str) -> bool:
    """True only for the first caller per kind per day (so a job runs once)."""
    with database.get_conn() as conn:
        row = conn.execute(
            "INSERT INTO notification_runs (kind, run_date, started_at) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING RETURNING kind",
            (kind, run_date, _now()),
        ).fetchone()
        return row is not None


# ---------------------------------------------------------------- push (FCM HTTP v1)
def save_device(user_id: int, token: str, platform: str = "android") -> None:
    with database.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO push_devices (token, user_id, platform, updated_at) VALUES (%s,%s,%s,%s)
            ON CONFLICT (token) DO UPDATE SET user_id = EXCLUDED.user_id, platform = EXCLUDED.platform, updated_at = EXCLUDED.updated_at
            """,
            (token, user_id, platform, _now()),
        )


def remove_device(token: str) -> None:
    with database.get_conn() as conn:
        conn.execute("DELETE FROM push_devices WHERE token = %s", (token,))


def device_tokens(user_ids: Iterable[int]) -> list[str]:
    ids = [int(u) for u in set(user_ids)]
    if not ids:
        return []
    with database.get_conn() as conn:
        rows = conn.execute("SELECT token FROM push_devices WHERE user_id = ANY(%s)", (ids,)).fetchall()
        return [r["token"] for r in rows]


_fcm_lock = threading.Lock()
_fcm_token: dict = {"value": None, "exp": 0}


def _service_account() -> Optional[dict]:
    raw = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        log.warning("FIREBASE_SERVICE_ACCOUNT_JSON is not valid JSON; push disabled")
        return None


def push_configured() -> bool:
    return _service_account() is not None


def _access_token(sa: dict) -> str:
    with _fcm_lock:
        if _fcm_token["value"] and _fcm_token["exp"] - 60 > time.time():
            return _fcm_token["value"]
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request

        creds = service_account.Credentials.from_service_account_info(
            sa, scopes=["https://www.googleapis.com/auth/firebase.messaging"])
        creds.refresh(Request())
        _fcm_token["value"] = creds.token
        _fcm_token["exp"] = creds.expiry.replace(tzinfo=timezone.utc).timestamp() if creds.expiry else time.time() + 1800
        return creds.token


def send_push(user_ids: Iterable[int], title: str, body: str, link: str = "#/home", tag: str = "general") -> int:
    sa = _service_account()
    if not sa:
        return 0
    tokens = device_tokens(user_ids)
    if not tokens:
        return 0
    try:
        access = _access_token(sa)
    except Exception as exc:
        log.warning("FCM auth failed: %s", exc)
        return 0
    url = f"https://fcm.googleapis.com/v1/projects/{sa.get('project_id')}/messages:send"
    sent = 0
    with httpx.Client(timeout=15.0) as client:
        for tok in tokens:
            is_chat = str(tag).startswith("chat")
            msg = {"message": {
                "token": tok,
                # A notification payload is shown by the phone itself even when the app is closed
                # (many vivo/Oppo/Xiaomi phones block data-only wake-ups). The data part carries
                # the link: tapping opens the app with it, and an open app builds its own.
                "notification": {"title": title[:120], "body": body[:400]},
                "data": {"title": title[:120], "body": body[:400], "link": link or "#/home", "tag": tag},
                "android": {
                    "priority": "HIGH",
                    "notification": {
                        "channel_id": "chat" if is_chat else "updates",
                        "tag": tag,
                        "icon": "ic_stat_notify",
                        "color": "#2457E6",
                        "default_sound": True,
                        "notification_priority": "PRIORITY_HIGH" if is_chat else "PRIORITY_DEFAULT",
                    },
                },
            }}
            try:
                r = client.post(url, json=msg, headers={"Authorization": f"Bearer {access}"})
                if r.status_code == 200:
                    sent += 1
                elif r.status_code in (400, 404) and ("UNREGISTERED" in r.text or "INVALID_ARGUMENT" in r.text):
                    remove_device(tok)
                else:
                    log.warning("FCM send failed %s: %s", r.status_code, r.text[:200])
            except Exception as exc:
                log.warning("FCM send error: %s", exc)
    return sent


def send_push_async(user_ids: Iterable[int], title: str, body: str, link: str = "#/home", tag: str = "general") -> None:
    ids = list(user_ids)
    if not ids or not push_configured():
        return
    threading.Thread(target=send_push, args=(ids, title, body, link, tag), daemon=True).start()


# ---------------------------------------------------------------- chat
def _direct_key(a: int, b: int) -> str:
    lo, hi = sorted((int(a), int(b)))
    return f"{lo}:{hi}"


def ensure_direct_thread(a: int, b: int) -> int:
    key = _direct_key(a, b)
    with database.get_conn() as conn:
        row = conn.execute("SELECT id FROM chat_threads WHERE direct_key = %s", (key,)).fetchone()
        if row:
            return int(row["id"])
        row = conn.execute(
            "INSERT INTO chat_threads (kind, direct_key, created_at) VALUES ('direct', %s, %s) "
            "ON CONFLICT (direct_key) DO UPDATE SET direct_key = EXCLUDED.direct_key RETURNING id",
            (key, _now()),
        ).fetchone()
        tid = int(row["id"])
        for uid in (a, b):
            conn.execute("INSERT INTO chat_members (thread_id, user_id, joined_at) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                         (tid, uid, _now()))
        return tid


def sync_group(group_key: str, title: str, member_ids: Iterable[int]) -> int:
    """Create/rename a team group and make its membership match member_ids exactly."""
    ids = sorted({int(u) for u in member_ids})
    with database.get_conn() as conn:
        row = conn.execute(
            "INSERT INTO chat_threads (kind, title, group_key, created_at) VALUES ('group', %s, %s, %s) "
            "ON CONFLICT (group_key) DO UPDATE SET title = EXCLUDED.title RETURNING id",
            (title, group_key, _now()),
        ).fetchone()
        tid = int(row["id"])
        if ids:
            conn.execute("DELETE FROM chat_members WHERE thread_id = %s AND NOT (user_id = ANY(%s))", (tid, ids))
        for uid in ids:
            conn.execute("INSERT INTO chat_members (thread_id, user_id, joined_at) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                         (tid, uid, _now()))
        return tid


def is_member(thread_id: int, user_id: int) -> bool:
    with database.get_conn() as conn:
        return conn.execute("SELECT 1 FROM chat_members WHERE thread_id = %s AND user_id = %s", (thread_id, user_id)).fetchone() is not None


def thread_member_ids(thread_id: int) -> list[int]:
    with database.get_conn() as conn:
        return [int(r["user_id"]) for r in conn.execute("SELECT user_id FROM chat_members WHERE thread_id = %s", (thread_id,)).fetchall()]


def list_threads(user_id: int) -> list[dict]:
    with database.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT t.id, t.kind, t.title, t.group_key, t.last_message_at, m.last_read_id,
                   (SELECT COUNT(*) FROM chat_members cm WHERE cm.thread_id = t.id) AS member_count,
                   (SELECT COUNT(*) FROM chat_messages x WHERE x.thread_id = t.id AND x.id > m.last_read_id AND x.sender_id <> %s) AS unread,
                   lm.kind AS last_kind, lm.body AS last_body, lm.sender_name AS last_sender, lm.retailer_name AS last_retailer,
                   other.id AS other_id, other.name AS other_name, other.role AS other_role
            FROM chat_members m
            JOIN chat_threads t ON t.id = m.thread_id
            LEFT JOIN LATERAL (SELECT kind, body, sender_name, retailer_name FROM chat_messages WHERE thread_id = t.id ORDER BY id DESC LIMIT 1) lm ON TRUE
            LEFT JOIN LATERAL (
                SELECT u.id, u.name, u.role FROM chat_members o JOIN users u ON u.id = o.user_id
                WHERE t.kind = 'direct' AND o.thread_id = t.id AND o.user_id <> %s LIMIT 1
            ) other ON TRUE
            WHERE m.user_id = %s
            ORDER BY COALESCE(t.last_message_at, t.created_at) DESC
            """,
            (user_id, user_id, user_id),
        ).fetchall()
        return [dict(r) for r in rows]


def chat_unread_total(user_id: int) -> int:
    with database.get_conn() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM chat_members m JOIN chat_messages x ON x.thread_id = m.thread_id
            WHERE m.user_id = %s AND x.id > m.last_read_id AND x.sender_id <> %s
            """,
            (user_id, user_id),
        ).fetchone()
        return int(row["n"])


def add_message(thread_id: int, sender: dict, kind: str, body: str = "", retailer_code: Optional[str] = None,
                retailer_name: Optional[str] = None, photo: Optional[bytes] = None, photo_mime: Optional[str] = None) -> dict:
    now = _now()
    with database.get_conn() as conn:
        row = conn.execute(
            """
            INSERT INTO chat_messages (thread_id, sender_id, sender_name, kind, body, retailer_code, retailer_name, photo, photo_mime, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id, thread_id, sender_id, sender_name, kind, body, retailer_code, retailer_name, photo_mime, created_at
            """,
            (thread_id, sender["id"], sender["name"], kind, body, retailer_code, retailer_name, photo, photo_mime, now),
        ).fetchone()
        conn.execute("UPDATE chat_threads SET last_message_at = %s WHERE id = %s", (now, thread_id))
        conn.execute("UPDATE chat_members SET last_read_id = %s WHERE thread_id = %s AND user_id = %s", (row["id"], thread_id, sender["id"]))
        return dict(row)


def list_messages(thread_id: int, after_id: int = 0, before_id: Optional[int] = None, limit: int = 60) -> list[dict]:
    with database.get_conn() as conn:
        if before_id:
            rows = conn.execute(
                "SELECT id, thread_id, sender_id, sender_name, kind, body, retailer_code, retailer_name, photo_mime, created_at "
                "FROM chat_messages WHERE thread_id = %s AND id < %s ORDER BY id DESC LIMIT %s",
                (thread_id, before_id, limit)).fetchall()
            return [dict(r) for r in reversed(rows)]
        if after_id:
            rows = conn.execute(
                "SELECT id, thread_id, sender_id, sender_name, kind, body, retailer_code, retailer_name, photo_mime, created_at "
                "FROM chat_messages WHERE thread_id = %s AND id > %s ORDER BY id LIMIT %s",
                (thread_id, after_id, limit)).fetchall()
            return [dict(r) for r in rows]
        rows = conn.execute(
            "SELECT id, thread_id, sender_id, sender_name, kind, body, retailer_code, retailer_name, photo_mime, created_at "
            "FROM chat_messages WHERE thread_id = %s ORDER BY id DESC LIMIT %s",
            (thread_id, limit)).fetchall()
        return [dict(r) for r in reversed(rows)]


def mark_thread_read(thread_id: int, user_id: int, last_id: int) -> None:
    with database.get_conn() as conn:
        conn.execute("UPDATE chat_members SET last_read_id = GREATEST(last_read_id, %s) WHERE thread_id = %s AND user_id = %s",
                     (last_id, thread_id, user_id))


def message_photo(message_id: int) -> Optional[dict]:
    with database.get_conn() as conn:
        row = conn.execute("SELECT thread_id, photo, photo_mime FROM chat_messages WHERE id = %s AND photo IS NOT NULL",
                           (message_id,)).fetchone()
        return dict(row) if row else None


def thread_info(thread_id: int) -> Optional[dict]:
    with database.get_conn() as conn:
        row = conn.execute("SELECT id, kind, title, group_key FROM chat_threads WHERE id = %s", (thread_id,)).fetchone()
        if not row:
            return None
        info = dict(row)
        info["members"] = [dict(r) for r in conn.execute(
            "SELECT u.id, u.name, u.role FROM chat_members m JOIN users u ON u.id = m.user_id WHERE m.thread_id = %s ORDER BY u.name",
            (thread_id,)).fetchall()]
        return info
