from __future__ import annotations

import hashlib
import hmac
import json
import logging
import sqlite3
import time
from pathlib import Path
from urllib.parse import parse_qsl

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from config import Settings
from database import Database

logger = logging.getLogger(__name__)
WEB_ROOT = Path(__file__).resolve().parent / "webapp"


class SettingsUpdate(BaseModel):
    enabled: bool


def verify_init_data(init_data: str, bot_token: str) -> dict:
    """Verify Telegram Mini App initData and return its authenticated user."""
    if not init_data or len(init_data) > 8192:
        raise HTTPException(status_code=401, detail="Telegram Mini App auth data is missing")
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
        values = dict(pairs)
        received_hash = values.pop("hash")
        auth_date = int(values["auth_date"])
        user = json.loads(values["user"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=401, detail="Invalid Telegram Mini App auth data")

    now = int(time.time())
    if auth_date > now + 60 or now - auth_date > 86400:
        raise HTTPException(status_code=401, detail="Telegram Mini App auth data has expired")

    check_string = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise HTTPException(status_code=401, detail="Telegram Mini App authentication failed")
    try:
        user_id = int(user["id"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Telegram user is missing from auth data")
    return {"id": user_id, "first_name": str(user.get("first_name") or ""),
            "username": str(user.get("username") or ""),
            "language_code": str(user.get("language_code") or "")}


def create_miniapp(settings: Settings, db: Database) -> FastAPI:
    app = FastAPI(title="Business Archive Mini App", docs_url=None, redoc_url=None)

    def owner_id(init_data: str | None) -> int:
        if init_data is None:
            raise HTTPException(status_code=401, detail="Open this app from Telegram")
        return verify_init_data(init_data, settings.bot_token)["id"]

    def require_admin(init_data: str | None) -> int:
        user_id = owner_id(init_data)
        if user_id not in settings.admin_ids:
            raise HTTPException(status_code=403, detail="Admin panel is restricted")
        return user_id

    async def serve_media(user_id: int, chat_id: int, message_id: int):
        row = await asyncio_to_thread(_media_row, db, user_id, chat_id, message_id)
        if not row or not row.get("file_path"):
            raise HTTPException(status_code=404, detail="Archived media not found")
        root = (settings.storage_dir / str(user_id)).resolve()
        path = Path(row["file_path"]).resolve()
        if root not in path.parents or not path.is_file():
            logger.warning("Rejected unsafe/missing media path for owner=%s", user_id)
            raise HTTPException(status_code=404, detail="Archived media not found")
        return FileResponse(path, filename=row.get("file_name") or path.name)

    @app.get("/", response_class=HTMLResponse)
    async def index():
        index_path = WEB_ROOT / "index.html"
        if not index_path.is_file():
            raise HTTPException(status_code=503, detail="Mini App frontend is not installed")
        return FileResponse(index_path)

    @app.get("/api/me")
    async def me(x_telegram_init_data: str | None = Header(default=None)):
        if x_telegram_init_data is None:
            raise HTTPException(status_code=401, detail="Open this app from Telegram")
        identity = verify_init_data(x_telegram_init_data, settings.bot_token)
        result = await asyncio_to_thread(_get_me, db, identity["id"])
        language = await db.language_for_owner(identity["id"])
        result.update(first_name=identity["first_name"], username=identity["username"],
                      language=language or ("ru" if identity["language_code"].lower().startswith("ru") else "uz"),
                      is_admin=identity["id"] in settings.admin_ids)
        return result

    @app.put("/api/language")
    async def update_language(body: dict,
                              x_telegram_init_data: str | None = Header(default=None)):
        user_id = owner_id(x_telegram_init_data)
        language = body.get("language") if isinstance(body, dict) else None
        if language not in {"uz", "ru"}:
            raise HTTPException(status_code=422, detail="language must be 'uz' or 'ru'")
        await db.set_language(user_id, language)
        return {"language": language}

    @app.get("/api/admin/overview")
    async def admin_overview(x_telegram_init_data: str | None = Header(default=None)):
        require_admin(x_telegram_init_data)
        return await asyncio_to_thread(_admin_overview, db)

    @app.get("/api/admin/users")
    async def admin_users(x_telegram_init_data: str | None = Header(default=None),
                          q: str = Query(default="", max_length=100),
                          limit: int = Query(default=100, ge=1, le=200)):
        require_admin(x_telegram_init_data)
        return {"items": await asyncio_to_thread(_admin_users, db, q, limit)}

    @app.get("/api/admin/users/{target_user_id}/chats")
    async def admin_chats(target_user_id: int, x_telegram_init_data: str | None = Header(default=None),
                          limit: int = Query(default=100, ge=1, le=200)):
        require_admin(x_telegram_init_data)
        return {"items": await asyncio_to_thread(_chats, db, target_user_id, limit)}

    @app.get("/api/admin/users/{target_user_id}/summary")
    async def admin_user_summary(target_user_id: int,
                                 x_telegram_init_data: str | None = Header(default=None)):
        require_admin(x_telegram_init_data)
        return await asyncio_to_thread(_admin_user_summary, db, target_user_id)

    @app.get("/api/admin/users/{target_user_id}/events")
    async def admin_events(target_user_id: int, x_telegram_init_data: str | None = Header(default=None),
                           limit: int = Query(default=100, ge=1, le=100),
                           chat_id: int | None = Query(default=None)):
        require_admin(x_telegram_init_data)
        return {"items": await asyncio_to_thread(_events, db, target_user_id, limit, chat_id)}

    @app.get("/api/admin/media/{target_user_id}/{message_id}")
    async def admin_media(target_user_id: int, message_id: int, chat_id: int,
                          x_telegram_init_data: str | None = Header(default=None)):
        require_admin(x_telegram_init_data)
        return await serve_media(target_user_id, chat_id, message_id)

    @app.post("/api/admin/users/{target_user_id}/pause")
    async def admin_pause_user(target_user_id: int,
                               x_telegram_init_data: str | None = Header(default=None)):
        require_admin(x_telegram_init_data)
        if not await db.connections_for_owner(target_user_id):
            raise HTTPException(status_code=404, detail="User is not registered")
        await db.set_owner_enabled(target_user_id, False)
        return {"user_id": target_user_id, "enabled": False}

    @app.get("/api/summary")
    async def summary(x_telegram_init_data: str | None = Header(default=None)):
        user_id = owner_id(x_telegram_init_data)
        return await asyncio_to_thread(_summary, db, user_id)

    @app.get("/api/messages")
    async def messages(
        x_telegram_init_data: str | None = Header(default=None),
        q: str = Query(default="", max_length=200),
        media: str = Query(default="all", pattern="^(all|photo|video|voice|video_note|text)$"),
        limit: int = Query(default=40, ge=1, le=100),
        offset: int = Query(default=0, ge=0, le=10000),
    ):
        user_id = owner_id(x_telegram_init_data)
        return {"items": await asyncio_to_thread(_messages, db, user_id, q, media, limit, offset)}

    @app.get("/api/chats")
    async def chats(x_telegram_init_data: str | None = Header(default=None),
                    limit: int = Query(default=100, ge=1, le=200)):
        user_id = owner_id(x_telegram_init_data)
        return {"items": await asyncio_to_thread(_chats, db, user_id, limit)}

    @app.get("/api/events")
    async def events(
        x_telegram_init_data: str | None = Header(default=None),
        limit: int = Query(default=40, ge=1, le=100),
        chat_id: int | None = Query(default=None),
    ):
        user_id = owner_id(x_telegram_init_data)
        return {"items": await asyncio_to_thread(_events, db, user_id, limit, chat_id)}

    @app.get("/api/media/{message_id}")
    async def media(
        message_id: int,
        chat_id: int,
        x_telegram_init_data: str | None = Header(default=None),
    ):
        user_id = owner_id(x_telegram_init_data)
        return await serve_media(user_id, chat_id, message_id)

    @app.put("/api/settings")
    async def update_settings(
        body: SettingsUpdate,
        x_telegram_init_data: str | None = Header(default=None),
    ):
        user_id = owner_id(x_telegram_init_data)
        connections = await db.connections_for_owner(user_id)
        if not connections:
            raise HTTPException(status_code=404, detail="No Business connection is registered")
        await db.set_owner_enabled(user_id, body.enabled)
        return {"enabled": body.enabled}

    return app


def _get_me(db: Database, user_id: int) -> dict:
    with db._connect() as c:
        connections = [dict(row) for row in c.execute(
            "SELECT enabled FROM connections WHERE owner_id=?", (user_id,)
        )]
    return {"user_id": user_id, "connected": len(connections),
            "enabled": any(item["enabled"] for item in connections)}


def _summary(db: Database, user_id: int) -> dict:
    with db._connect() as c:
        messages = c.execute("SELECT COUNT(*) FROM messages WHERE owner_id=?", (user_id,)).fetchone()[0]
        chats = c.execute("SELECT COUNT(DISTINCT chat_id) FROM messages WHERE owner_id=?", (user_id,)).fetchone()[0]
        media_count, media_bytes = c.execute(
            "SELECT COUNT(*),COALESCE(SUM(file_size),0) FROM messages WHERE owner_id=? AND file_path IS NOT NULL",
            (user_id,),
        ).fetchone()
        deleted = c.execute("SELECT COUNT(*) FROM messages WHERE owner_id=? AND is_deleted=1",
                            (user_id,)).fetchone()[0]
        edited = c.execute("""SELECT COUNT(*) FROM revisions r JOIN connections c USING(connection_id)
            WHERE c.owner_id=?""", (user_id,)).fetchone()[0]
        connections = [dict(row) for row in c.execute("SELECT enabled FROM connections WHERE owner_id=?", (user_id,))]
    return {"messages": messages, "chats": chats, "media": media_count, "media_bytes": media_bytes,
            "deleted": deleted, "edited": edited, "connected": len(connections),
            "enabled": any(row["enabled"] for row in connections)}


def _messages(db: Database, user_id: int, q: str, media: str, limit: int, offset: int) -> list[dict]:
    clauses = ["owner_id=?"]
    params: list = [user_id]
    if q:
        clauses.append("(text LIKE ? OR chat_title LIKE ? OR sender_name LIKE ? OR sender_username LIKE ?)")
        needle = f"%{q}%"
        params.extend([needle, needle, needle, needle])
    if media == "text":
        clauses.append("media_type IS NULL")
    elif media != "all":
        clauses.append("media_type=?")
        params.append(media)
    params.extend([limit, offset])
    with db._connect() as c:
        rows = [dict(row) for row in c.execute(
            f"SELECT * FROM messages WHERE {' AND '.join(clauses)} ORDER BY sent_at DESC LIMIT ? OFFSET ?", params
        )]
    for row in rows:
        row["has_file"] = bool(row.get("file_path"))
        row.pop("file_path", None)
    return rows


def _events(db: Database, user_id: int, limit: int, chat_id: int | None = None) -> list[dict]:
    chat_filter = " WHERE chat_id=?" if chat_id is not None else ""
    order = "DESC"
    sql = """SELECT * FROM (
        SELECT 'message' AS event_type,m.chat_id,m.message_id,
               COALESCE((SELECT MAX(d.deleted_at) FROM deletions d WHERE d.connection_id=m.connection_id
                         AND d.chat_id=m.chat_id AND d.message_id=m.message_id),m.sent_at) AS occurred_at,
               NULL AS old_text,m.text AS new_text,m.media_type,m.file_name,m.sender_name,m.sender_username,
               m.chat_title,m.is_deleted,(m.file_path IS NOT NULL) AS has_file
          FROM messages m WHERE m.owner_id=?
        UNION ALL
        SELECT 'edit',r.chat_id,r.message_id,r.edited_at,r.old_text,r.new_text,NULL,NULL,
               r.sender_name,r.sender_username,
               COALESCE(r.chat_title,(SELECT m.chat_title FROM messages m WHERE m.connection_id=r.connection_id
                    AND m.chat_id=r.chat_id AND m.message_id=r.message_id LIMIT 1)),0,0
          FROM revisions r JOIN connections c USING(connection_id) WHERE c.owner_id=?
        )""" + chat_filter + f" ORDER BY occurred_at {order} LIMIT ?"
    params = [user_id, user_id]
    if chat_id is not None:
        params.append(chat_id)
    params.append(limit)
    with db._connect() as c:
        rows = [dict(row) for row in c.execute(sql, params)]
    if chat_id is not None:
        rows.reverse()  # Show the newest bounded slice in conversation order.
    return rows


def _chats(db: Database, user_id: int, limit: int) -> list[dict]:
    sql = """SELECT chat_id,COUNT(*) AS event_count,MAX(occurred_at) AS latest_at,
                    MAX(CASE WHEN rank_num=1 THEN preview END) AS preview,MAX(chat_title) AS chat_title
             FROM (
               SELECT chat_id,occurred_at,preview,chat_title,
                      ROW_NUMBER() OVER(PARTITION BY chat_id ORDER BY occurred_at DESC) AS rank_num
               FROM (
                 SELECT r.chat_id,r.edited_at AS occurred_at,r.chat_title,
                        COALESCE(r.new_text,'Matn tahrirlandi') AS preview
                   FROM revisions r JOIN connections c USING(connection_id) WHERE c.owner_id=?
                 UNION ALL
                 SELECT m.chat_id,m.sent_at AS occurred_at,m.chat_title,
                        COALESCE(m.text,m.media_type,'Xabar') AS preview
                   FROM messages m WHERE m.owner_id=?
               )
             ) AS events GROUP BY chat_id ORDER BY latest_at DESC LIMIT ?"""
    with db._connect() as c:
        return [dict(row) for row in c.execute(sql, (user_id, user_id, limit))]


def _admin_user_summary(db: Database, user_id: int) -> dict:
    return _summary(db, user_id)


def _media_row(db: Database, user_id: int, chat_id: int, message_id: int) -> dict | None:
    with db._connect() as c:
        row = c.execute("SELECT file_path,file_name FROM messages WHERE owner_id=? AND chat_id=? AND message_id=?",
                        (user_id, chat_id, message_id)).fetchone()
        return dict(row) if row else None


def _admin_overview(db: Database) -> dict:
    with db._connect() as c:
        users = c.execute("SELECT COUNT(DISTINCT owner_id) FROM connections").fetchone()[0]
        active = c.execute("SELECT COUNT(DISTINCT owner_id) FROM connections WHERE enabled=1").fetchone()[0]
        edits = c.execute("SELECT COUNT(*) FROM revisions").fetchone()[0]
        deleted_media, cached_bytes = c.execute(
            "SELECT COUNT(*),COALESCE(SUM(file_size),0) FROM messages WHERE is_deleted=1 AND media_type IS NOT NULL"
        ).fetchone()
        total_cached_bytes = c.execute(
            "SELECT COALESCE(SUM(file_size),0) FROM messages WHERE file_path IS NOT NULL"
        ).fetchone()[0]
    return {"users": users, "active_users": active, "edits": edits,
            "deleted_media": deleted_media, "deleted_media_bytes": cached_bytes,
            "cached_bytes": total_cached_bytes}


def _admin_users(db: Database, q: str, limit: int) -> list[dict]:
    clauses: list[str] = []
    params: list = []
    if q:
        needle = f"%{q}%"
        clauses.append("(CAST(c.owner_id AS TEXT) LIKE ? OR c.owner_name LIKE ? OR c.owner_username LIKE ?)")
        params.extend((needle, needle, needle))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    sql = f"""SELECT c.owner_id,MAX(c.owner_name) AS owner_name,MAX(c.owner_username) AS owner_username,
                    COUNT(*) AS connections,SUM(c.enabled) AS enabled_connections,
                    (SELECT COUNT(*) FROM revisions r JOIN connections rc USING(connection_id)
                      WHERE rc.owner_id=c.owner_id) AS edit_count,
                    (SELECT COUNT(*) FROM messages m WHERE m.owner_id=c.owner_id
                      AND m.is_deleted=1 AND m.media_type IS NOT NULL) AS deleted_media,
                    (SELECT COALESCE(SUM(file_size),0) FROM messages m WHERE m.owner_id=c.owner_id
                      AND m.file_path IS NOT NULL) AS cached_bytes
             FROM connections c {where} GROUP BY c.owner_id ORDER BY MAX(c.updated_at) DESC LIMIT ?"""
    with db._connect() as c:
        rows = [dict(row) for row in c.execute(sql, params)]
    for row in rows:
        row["enabled"] = bool(row.pop("enabled_connections") or 0)
    return rows


async def asyncio_to_thread(function, *args):
    import asyncio
    return await asyncio.to_thread(function, *args)
