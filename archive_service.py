from __future__ import annotations

import logging
import os
import re
import uuid
from pathlib import Path

from aiogram import Bot
from aiogram.types import Message

from database import Database

logger = logging.getLogger(__name__)


def business_chat_title(chat, chat_id: int) -> str:
    """Use Telegram's visible chat name; Bot API cannot read a phone contact alias."""
    title = getattr(chat, "title", None)
    if title:
        return str(title)
    names = [getattr(chat, "first_name", None), getattr(chat, "last_name", None)]
    full_name = " ".join(str(part).strip() for part in names if part and str(part).strip())
    if full_name:
        return full_name
    username = getattr(chat, "username", None)
    if username:
        return f"@{username}"
    return "Telegram chat"


class ArchiveService:
    """Archives ordinary Business Bot API messages delivered to this bot."""

    def __init__(self, bot: Bot, db: Database, storage_root: Path, max_download_mb: int) -> None:
        self.bot = bot
        self.db = db
        self.storage_root = storage_root
        self.max_bytes = max_download_mb * 1024 * 1024

    @staticmethod
    def _media(message: Message):
        if message.photo:
            item = message.photo[-1]
            return "photo", item.file_id, item.file_unique_id, item.file_size, ".jpg"
        if message.video:
            item = message.video
            return "video", item.file_id, item.file_unique_id, item.file_size, Path(
                item.file_name or "video.mp4").suffix or ".mp4"
        if message.voice:
            item = message.voice
            return "voice", item.file_id, item.file_unique_id, item.file_size, ".ogg"
        if message.video_note:
            item = message.video_note
            return "video_note", item.file_id, item.file_unique_id, item.file_size, ".mp4"

        # Bir martalik yoki yashirin media xabarlarni document sifatida tutib qolish
        if message.document:
            item = message.document
            return "photo", item.file_id, item.file_unique_id, item.file_size, ".jpg"

        if message.animation:
            item = message.animation
            return "video", item.file_id, item.file_unique_id, item.file_size, ".mp4"
        return None

    async def _download(self, owner_id: int, chat_id: int, message: Message) -> tuple[str, str, int] | None:
        media = self._media(message)
        if not media:
            return None
        media_type, file_id, unique_id, size, extension = media
        if message.has_protected_content:
            logger.warning("Media unavailable: protected content owner=%s chat=%s message=%s",
                           owner_id, chat_id, message.message_id)
            return None
        if size is not None and size > self.max_bytes:
            logger.warning("Media exceeds configured Bot API download limit owner=%s chat=%s message=%s size=%s limit=%s",
                           owner_id, chat_id, message.message_id, size, self.max_bytes)
            return None
        folder = self.storage_root / str(owner_id) / str(chat_id)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{message.message_id}_{unique_id}{extension}"
        temporary = folder / f".{uuid.uuid4().hex}.part"
        try:
            remote = await self.bot.get_file(file_id)
            if remote.file_size is not None and remote.file_size > self.max_bytes:
                logger.warning("Telegram file exceeds configured download limit owner=%s chat=%s message=%s size=%s limit=%s",
                               owner_id, chat_id, message.message_id, remote.file_size, self.max_bytes)
                return None
            await self.bot.download_file(remote.file_path, destination=temporary)
            actual_size = temporary.stat().st_size
            if actual_size > self.max_bytes:
                temporary.unlink(missing_ok=True)
                return None
            os.replace(temporary, target)
            return media_type, str(target), actual_size
        except Exception:
            temporary.unlink(missing_ok=True)
            logger.exception("Media download failed for owner=%s message=%s", owner_id, message.message_id)
            return None

    async def capture(self, message: Message, owner_id: int, connection_id: str) -> tuple[str | None, str | None]:
        chat_id = message.chat.id
        media_type = file_path = file_name = None
        file_size = None
        result = await self._download(owner_id, chat_id, message)
        if result:
            media_type, file_path, file_size = result
            file_name = Path(file_path).name
        elif self._media(message):
            media_type = self._media(message)[0]

        sender_id = message.from_user.id if message.from_user else None
        sender_name = None
        sender_username = None
        if message.from_user:
            sender_name = " ".join(part for part in
                                   (message.from_user.first_name, message.from_user.last_name) if part)
            sender_username = message.from_user.username

        await self.db.archive(
            owner_id=owner_id,
            connection_id=connection_id,
            chat_id=chat_id,
            message_id=message.message_id,
            sender_id=sender_id,
            sender_name=sender_name or None,
            sender_username=sender_username,
            chat_title=business_chat_title(message.chat, chat_id),
            sent_at=message.date.isoformat() if message.date else None,
            text=message.text or message.caption,
            media_type=media_type,
            file_path=file_path,
            file_name=file_name,
            file_size=file_size,
        )
        return media_type, file_path


def safe_text(value: str | None, limit: int = 3500) -> str:
    value = value or "(no text)"
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", value)[:limit]