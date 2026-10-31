"""HTTP routes for notifications, push device registration and team chat."""
from __future__ import annotations

import threading
import time
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import crud, engage
from .alignment import alignment, canonical_name
from .auth import get_current_user

router = APIRouter()

ROLE_ORDER = {"CEO": -1, "KAM": 0, "SS": 1, "TL": 2, "RDS": 3}


def me(user: dict = Depends(get_current_user)) -> dict:
    """The logged-in field user's database record (chat and notifications are per person)."""
    rec = engage.user_by_username(str(user.get("sub") or ""))
    if not rec:
        raise HTTPException(status_code=403, detail="Chat and notifications are for team logins (PIN or username).")
    return rec


# ---------------------------------------------------------------- team groups
_group_sync = {"at": 0.0}
_group_lock = threading.Lock()


def team_groups() -> list[tuple[str, str, list[int]]]:
    """(group_key, title, member ids) built from the alignment: Zone A, each KAM's team, each SS's team."""
    users = engage.active_users()
    by_role_name = {(u["role"], canonical_name(u["name"])): u["id"] for u in users}
    groups = [("zone:A", "Zone A · Everyone", [u["id"] for u in users])]
    kam_members: dict = {}
    ss_members: dict = {}
    for row in alignment.rows:
        kam, ss = canonical_name(row.get("kam")), canonical_name(row.get("ss"))
        people = [("TL", canonical_name(row.get("tl"))), ("SS", ss), ("RDS", canonical_name(row.get("rds")))]
        ids = [by_role_name.get(p) for p in people if by_role_name.get(p)]
        if kam:
            kam_members.setdefault(kam, set()).update(ids)
        if ss:
            tl_id = by_role_name.get(("TL", canonical_name(row.get("tl"))))
            if tl_id:
                ss_members.setdefault(ss, set()).add(tl_id)
    for kam, ids in sorted(kam_members.items()):
        kid = by_role_name.get(("KAM", kam))
        if kid:
            groups.append((f"kam:{kam}", f"Team {kam}", sorted(ids | {kid})))
    for ss, ids in sorted(ss_members.items()):
        sid = by_role_name.get(("SS", ss))
        if sid and ids:
            groups.append((f"ss:{ss}", f"SS {ss} · TLs", sorted(ids | {sid})))
    return groups


def sync_groups(force: bool = False) -> None:
    with _group_lock:
        if not force and time.time() - _group_sync["at"] < 600:
            return
        for key, title, ids in team_groups():
            engage.sync_group(key, title, ids)
        _group_sync["at"] = time.time()


# ---------------------------------------------------------------- notifications
class ReadIn(BaseModel):
    ids: Optional[List[int]] = None


class DeviceIn(BaseModel):
    token: str = Field(..., min_length=10, max_length=4096)
    platform: str = Field(default="android", max_length=20)


@router.get("/notifications")
def notifications(limit: int = Query(default=50, ge=1, le=200), who: dict = Depends(me)):
    return {
        "items": engage.list_notifications(who["id"], limit),
        "unread": engage.unread_count(who["id"]),
        "chat_unread": engage.chat_unread_total(who["id"]),
        "push_enabled": engage.push_configured(),
    }


@router.get("/notifications/counts")
def notification_counts(who: dict = Depends(me)):
    return {"unread": engage.unread_count(who["id"]), "chat_unread": engage.chat_unread_total(who["id"])}


@router.post("/notifications/read")
def notifications_read(payload: ReadIn, who: dict = Depends(me)):
    return {"updated": engage.mark_notifications_read(who["id"], payload.ids)}


@router.post("/devices")
def register_device(payload: DeviceIn, who: dict = Depends(me)):
    engage.save_device(who["id"], payload.token.strip(), payload.platform)
    return {"ok": True, "push_enabled": engage.push_configured()}


@router.post("/devices/remove")
def unregister_device(payload: DeviceIn, who: dict = Depends(me)):
    engage.remove_device(payload.token.strip())
    return {"ok": True}


# ---------------------------------------------------------------- chat
class DirectIn(BaseModel):
    user_id: int


class MessageIn(BaseModel):
    kind: str = Field(default="text", pattern="^(text|retailer)$")
    body: str = Field(default="", max_length=4000)
    retailer_code: Optional[str] = Field(default=None, max_length=40)


class ThreadReadIn(BaseModel):
    last_id: int = Field(..., ge=0)


def _thread_or_403(thread_id: int, who: dict) -> dict:
    info = engage.thread_info(thread_id)
    if not info or not engage.is_member(thread_id, who["id"]):
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return info


def _title(info: dict, who: dict) -> str:
    if info["kind"] == "group":
        return info.get("title") or "Group"
    other = next((m for m in info["members"] if m["id"] != who["id"]), None)
    return f"{other['name']}" if other else "Chat"


def _notify_members(thread_id: int, info: dict, sender: dict, preview: str) -> None:
    others = [m for m in engage.thread_member_ids(thread_id) if m != sender["id"]]
    if not others:
        return
    title = sender["name"] if info["kind"] == "direct" else f"{sender['name']} · {info.get('title') or 'Group'}"
    engage.send_push_async(others, title, preview, f"#/chat/{thread_id}", tag=f"chat-{thread_id}")


@router.get("/chat/people")
def chat_people(search: Optional[str] = None, who: dict = Depends(me)):
    q = (search or "").strip().lower()
    people = [u for u in engage.active_users() if u["id"] != who["id"]]
    if q:
        people = [u for u in people if q in u["name"].lower() or q in u["role"].lower()]
    people.sort(key=lambda u: (ROLE_ORDER.get(u["role"], 9), u["name"]))
    return [{"id": u["id"], "name": u["name"], "role": u["role"]} for u in people[:200]]


@router.get("/chat/threads")
def chat_threads(who: dict = Depends(me)):
    try:
        sync_groups()
    except Exception:
        pass  # groups catch up on the next call
    out = []
    for t in engage.list_threads(who["id"]):
        if t["kind"] == "direct" and not t.get("last_message_at"):
            continue  # hide empty 1:1 chats
        if t["kind"] == "direct":
            title, subtitle = t.get("other_name") or "Chat", t.get("other_role") or ""
        else:
            title, subtitle = t.get("title") or "Group", f"{t['member_count']} members"
        last = None
        if t.get("last_kind"):
            body = t.get("last_body") or ""
            if t["last_kind"] == "photo":
                body = "📷 Photo" + (f" · {body}" if body else "")
            elif t["last_kind"] == "retailer":
                body = f"🏪 {t.get('last_retailer') or 'Retailer'}" + (f" · {body}" if body else "")
            last = {"sender": t.get("last_sender"), "text": body}
        out.append({"id": t["id"], "kind": t["kind"], "title": title, "subtitle": subtitle,
                    "last": last, "last_message_at": t.get("last_message_at"), "unread": int(t["unread"] or 0)})
    return out


@router.post("/chat/direct")
def chat_direct(payload: DirectIn, who: dict = Depends(me)):
    if payload.user_id == who["id"]:
        raise HTTPException(status_code=400, detail="Pick someone else to chat with.")
    if not any(u["id"] == payload.user_id for u in engage.active_users()):
        raise HTTPException(status_code=404, detail="That person isn't an active user.")
    return {"id": engage.ensure_direct_thread(who["id"], payload.user_id)}


@router.get("/chat/threads/{thread_id}")
def chat_thread(thread_id: int, after: int = 0, before: Optional[int] = None, who: dict = Depends(me)):
    info = _thread_or_403(thread_id, who)
    msgs = engage.list_messages(thread_id, after_id=after, before_id=before)
    return {"id": thread_id, "kind": info["kind"], "title": _title(info, who),
            "members": info["members"], "me": who["id"], "messages": msgs}


@router.post("/chat/threads/{thread_id}/messages")
def chat_send(thread_id: int, payload: MessageIn, who: dict = Depends(me)):
    info = _thread_or_403(thread_id, who)
    body = payload.body.strip()
    retailer_name = None
    code = None
    if payload.kind == "retailer":
        code = (payload.retailer_code or "").strip().upper()
        r = crud.lookup_retailer_by_code(code)
        if not r:
            raise HTTPException(status_code=404, detail="Retailer not found.")
        retailer_name = r.get("name")
        preview = f"🏪 {retailer_name}" + (f" — {body}" if body else "")
    else:
        if not body:
            raise HTTPException(status_code=400, detail="Type a message.")
        preview = body
    msg = engage.add_message(thread_id, who, payload.kind, body, code, retailer_name)
    _notify_members(thread_id, info, who, preview[:200])
    return msg


@router.post("/chat/threads/{thread_id}/photo")
async def chat_photo(thread_id: int, file: UploadFile = File(...), caption: str = Form(default=""), who: dict = Depends(me)):
    info = _thread_or_403(thread_id, who)
    if file.content_type not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(status_code=400, detail="Only JPG, PNG or WEBP photos.")
    data = await file.read()
    if len(data) > 4 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Photo must be 4 MB or smaller.")
    msg = engage.add_message(thread_id, who, "photo", caption.strip()[:1000], photo=data, photo_mime=file.content_type)
    _notify_members(thread_id, info, who, "📷 Photo" + (f" — {caption.strip()}" if caption.strip() else ""))
    return msg


@router.get("/chat/photos/{message_id}")
def chat_photo_get(message_id: int, who: dict = Depends(me)):
    p = engage.message_photo(message_id)
    if not p or not engage.is_member(int(p["thread_id"]), who["id"]):
        raise HTTPException(status_code=404, detail="Photo not found.")
    return Response(content=bytes(p["photo"]), media_type=p["photo_mime"] or "image/jpeg",
                    headers={"Cache-Control": "private, max-age=86400"})


@router.post("/chat/threads/{thread_id}/read")
def chat_read(thread_id: int, payload: ThreadReadIn, who: dict = Depends(me)):
    _thread_or_403(thread_id, who)
    engage.mark_thread_read(thread_id, who["id"], payload.last_id)
    return {"ok": True}
