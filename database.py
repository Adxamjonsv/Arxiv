from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any


class Database:
    """Small SQLite repository. Each operation owns its connection; writes are serialized."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._write_lock = asyncio.Lock()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize)

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript("""
                CREATE TABLE IF NOT EXISTS connections (
                    connection_id TEXT PRIMARY KEY,
                    owner_id INTEGER NOT NULL,
                    owner_name TEXT,
                    owner_username TEXT,
                    notify_chat_id INTEGER NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS messages (
                    owner_id INTEGER NOT NULL,
                    connection_id TEXT NOT NULL,
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    sender_id INTEGER,
                    sender_name TEXT,
                    sender_username TEXT,
                    chat_title TEXT,
                    sent_at TEXT,
                    text TEXT,
                    media_type TEXT,
                    file_path TEXT,
                    file_name TEXT,
                    file_size INTEGER,
                    is_deleted INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(connection_id, chat_id, message_id)
                );
                CREATE TABLE IF NOT EXISTS revisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    connection_id TEXT NOT NULL,
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    old_text TEXT,
                    new_text TEXT,
                    chat_title TEXT,
                    sender_name TEXT,
                    sender_username TEXT,
                    edited_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS deletions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    connection_id TEXT NOT NULL,
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    deleted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS user_preferences (
                    owner_id INTEGER PRIMARY KEY,
                    language TEXT NOT NULL DEFAULT 'uz' CHECK(language IN ('uz','ru')),
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS messages_owner_idx ON messages(owner_id, sent_at);
            """)
            columns = {row[1] for row in c.execute("PRAGMA table_info(messages)")}
            if "chat_title" not in columns:
                c.execute("ALTER TABLE messages ADD COLUMN chat_title TEXT")
            if "sender_name" not in columns:
                c.execute("ALTER TABLE messages ADD COLUMN sender_name TEXT")
            if "sender_username" not in columns:
                c.execute("ALTER TABLE messages ADD COLUMN sender_username TEXT")
            connection_columns = {row[1] for row in c.execute("PRAGMA table_info(connections)")}
            if "owner_name" not in connection_columns:
                c.execute("ALTER TABLE connections ADD COLUMN owner_name TEXT")
            if "owner_username" not in connection_columns:
                c.execute("ALTER TABLE connections ADD COLUMN owner_username TEXT")
            revision_columns = {row[1] for row in c.execute("PRAGMA table_info(revisions)")}
            if "chat_title" not in revision_columns:
                c.execute("ALTER TABLE revisions ADD COLUMN chat_title TEXT")
            if "sender_name" not in revision_columns:
                c.execute("ALTER TABLE revisions ADD COLUMN sender_name TEXT")
            if "sender_username" not in revision_columns:
                c.execute("ALTER TABLE revisions ADD COLUMN sender_username TEXT")

    async def language_for_owner(self, owner_id: int) -> str | None:
        return await asyncio.to_thread(self._language_for_owner, owner_id)

    def _language_for_owner(self, owner_id: int) -> str | None:
        with self._connect() as c:
            row = c.execute("SELECT language FROM user_preferences WHERE owner_id=?", (owner_id,)).fetchone()
            return str(row[0]) if row else None

    async def set_language(self, owner_id: int, language: str) -> None:
        if language not in {"uz", "ru"}:
            raise ValueError("language must be 'uz' or 'ru'")
        async with self._write_lock:
            await asyncio.to_thread(self._set_language, owner_id, language)

    def _set_language(self, owner_id: int, language: str) -> None:
        with self._connect() as c:
            c.execute("""INSERT INTO user_preferences(owner_id,language) VALUES(?,?)
                ON CONFLICT(owner_id) DO UPDATE SET language=excluded.language,updated_at=CURRENT_TIMESTAMP""",
                (owner_id, language))

    async def save_connection(self, connection_id: str, owner_id: int, notify_chat_id: int, enabled: bool,
                              owner_name: str | None = None, owner_username: str | None = None) -> None:
        async with self._write_lock:
            await asyncio.to_thread(self._save_connection, connection_id, owner_id, notify_chat_id, enabled,
                                    owner_name, owner_username)

    def _save_connection(self, connection_id: str, owner_id: int, notify_chat_id: int, enabled: bool,
                         owner_name: str | None, owner_username: str | None) -> None:
        with self._connect() as c:
            c.execute("""INSERT INTO connections(connection_id,owner_id,owner_name,owner_username,notify_chat_id,enabled)
                VALUES(?,?,?,?,?,?) ON CONFLICT(connection_id) DO UPDATE SET owner_id=excluded.owner_id,
                owner_name=COALESCE(excluded.owner_name,connections.owner_name),
                owner_username=COALESCE(excluded.owner_username,connections.owner_username),
                notify_chat_id=excluded.notify_chat_id,enabled=excluded.enabled,updated_at=CURRENT_TIMESTAMP""",
                (connection_id, owner_id, owner_name, owner_username, notify_chat_id, int(enabled)))

    async def connection(self, connection_id: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._connection, connection_id)

    def _connection(self, connection_id: str) -> dict[str, Any] | None:
        with self._connect() as c:
            row = c.execute("SELECT * FROM connections WHERE connection_id=?", (connection_id,)).fetchone()
            return dict(row) if row else None

    async def set_owner_enabled(self, owner_id: int, enabled: bool) -> None:
        async with self._write_lock:
            await asyncio.to_thread(self._set_owner_enabled, owner_id, enabled)

    def _set_owner_enabled(self, owner_id: int, enabled: bool) -> None:
        with self._connect() as c:
            c.execute("UPDATE connections SET enabled=?,updated_at=CURRENT_TIMESTAMP WHERE owner_id=?",
                      (int(enabled), owner_id))

    async def connections_for_owner(self, owner_id: int) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._connections_for_owner, owner_id)

    def _connections_for_owner(self, owner_id: int) -> list[dict[str, Any]]:
        with self._connect() as c:
            return [dict(row) for row in c.execute("SELECT * FROM connections WHERE owner_id=?", (owner_id,))]

    async def archive(self, **data: Any) -> None:
        async with self._write_lock:
            await asyncio.to_thread(self._archive, data)

    def _archive(self, d: dict[str, Any]) -> None:
        with self._connect() as c:
            c.execute("""INSERT INTO messages(owner_id,connection_id,chat_id,message_id,sender_id,sender_name,
                sender_username,chat_title,sent_at,text,
                media_type,file_path,file_name,file_size) VALUES(:owner_id,:connection_id,:chat_id,:message_id,
                :sender_id,:sender_name,:sender_username,:chat_title,:sent_at,:text,:media_type,:file_path,:file_name,:file_size)
                ON CONFLICT(connection_id,chat_id,message_id) DO UPDATE SET text=excluded.text,
                media_type=COALESCE(excluded.media_type,messages.media_type),
                file_path=COALESCE(excluded.file_path,messages.file_path),
                file_name=COALESCE(excluded.file_name,messages.file_name),
                file_size=COALESCE(excluded.file_size,messages.file_size),
                chat_title=COALESCE(excluded.chat_title,messages.chat_title),
                sender_name=COALESCE(excluded.sender_name,messages.sender_name),
                sender_username=COALESCE(excluded.sender_username,messages.sender_username),
                updated_at=CURRENT_TIMESTAMP""", d)

    async def message(self, connection_id: str, chat_id: int, message_id: int) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._message, connection_id, chat_id, message_id)

    async def set_chat_title(self, connection_id: str, chat_id: int, message_id: int, chat_title: str) -> None:
        async with self._write_lock:
            await asyncio.to_thread(self._set_chat_title, connection_id, chat_id, message_id, chat_title)

    def _set_chat_title(self, connection_id: str, chat_id: int, message_id: int, chat_title: str) -> None:
        with self._connect() as c:
            c.execute("UPDATE messages SET chat_title=? WHERE connection_id=? AND chat_id=? AND message_id=?",
                      (chat_title, connection_id, chat_id, message_id))

    def _message(self, connection_id: str, chat_id: int, message_id: int) -> dict[str, Any] | None:
        with self._connect() as c:
            row = c.execute("SELECT * FROM messages WHERE connection_id=? AND chat_id=? AND message_id=?",
                            (connection_id, chat_id, message_id)).fetchone()
            return dict(row) if row else None

    async def edit(self, connection_id: str, chat_id: int, message_id: int, old: str | None,
                   new: str | None, chat_title: str | None = None,
                   sender_name: str | None = None, sender_username: str | None = None) -> None:
        async with self._write_lock:
            await asyncio.to_thread(self._edit, connection_id, chat_id, message_id, old, new,
                                    chat_title, sender_name, sender_username)

    def _edit(self, connection_id: str, chat_id: int, message_id: int, old: str | None,
              new: str | None, chat_title: str | None, sender_name: str | None,
              sender_username: str | None) -> None:
        with self._connect() as c:
            c.execute("INSERT INTO revisions(connection_id,chat_id,message_id,old_text,new_text,chat_title,sender_name,sender_username) VALUES(?,?,?,?,?,?,?,?)",
                      (connection_id, chat_id, message_id, old, new, chat_title, sender_name, sender_username))
            c.execute("UPDATE messages SET text=?,updated_at=CURRENT_TIMESTAMP WHERE connection_id=? AND chat_id=? AND message_id=?",
                      (new, connection_id, chat_id, message_id))

    async def deleted(self, connection_id: str, chat_id: int, message_id: int,
                      owner_id: int | None = None, chat_title: str | None = None) -> dict[str, Any] | None:
        async with self._write_lock:
            return await asyncio.to_thread(self._deleted, connection_id, chat_id, message_id, owner_id, chat_title)

    def _deleted(self, connection_id: str, chat_id: int, message_id: int,
                 owner_id: int | None, chat_title: str | None) -> dict[str, Any] | None:
        with self._connect() as c:
            row = c.execute("SELECT * FROM messages WHERE connection_id=? AND chat_id=? AND message_id=?",
                            (connection_id, chat_id, message_id)).fetchone()
            if row is None and owner_id is not None:
                c.execute("""INSERT OR IGNORE INTO messages(owner_id,connection_id,chat_id,message_id,
                    chat_title,text,is_deleted) VALUES(?,?,?,?,?,?,1)""",
                    (owner_id, connection_id, chat_id, message_id, chat_title,
                     "(Xabar o‘chirilishidan oldin arxivga kelmagan)"))
                row = c.execute("SELECT * FROM messages WHERE connection_id=? AND chat_id=? AND message_id=?",
                                (connection_id, chat_id, message_id)).fetchone()
            c.execute("INSERT INTO deletions(connection_id,chat_id,message_id) VALUES(?,?,?)",
                      (connection_id, chat_id, message_id))
            c.execute("UPDATE messages SET is_deleted=1 WHERE connection_id=? AND chat_id=? AND message_id=?",
                      (connection_id, chat_id, message_id))
            return dict(row) if row else None
