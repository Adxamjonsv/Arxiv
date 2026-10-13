from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    bot_token: str
    database_path: Path
    storage_dir: Path
    max_download_mb: int
    log_level: str
    mini_app_url: str
    mini_app_host: str
    mini_app_port: int
    admin_ids: tuple[int, ...]

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError("BOT_TOKEN must be set in the environment")
        max_download_mb = int(os.getenv("MAX_DOWNLOAD_MB", "20"))
        if not 1 <= max_download_mb <= 20:
            raise RuntimeError("MAX_DOWNLOAD_MB must be between 1 and 20 for the standard Telegram Bot API")
        mini_app_url = os.getenv("MINI_APP_URL", "").strip().rstrip("/")
        if mini_app_url and not mini_app_url.startswith("https://"):
            raise RuntimeError("MINI_APP_URL must use HTTPS so Telegram can open the Mini App")
        mini_app_port = int(os.getenv("MINI_APP_PORT", "8080"))
        if not 1 <= mini_app_port <= 65535:
            raise RuntimeError("MINI_APP_PORT must be between 1 and 65535")
        raw_admin_ids = os.getenv("ADMIN_IDS", "")
        try:
            admin_ids = tuple(sorted({int(value.strip()) for value in raw_admin_ids.split(",") if value.strip()}))
        except ValueError as exc:
            raise RuntimeError("ADMIN_IDS must be a comma-separated list of Telegram numeric IDs") from exc
        if any(user_id <= 0 for user_id in admin_ids):
            raise RuntimeError("ADMIN_IDS must contain positive Telegram user IDs")
        return cls(
            bot_token=token,
            database_path=Path(os.getenv("DATABASE_PATH", "archive.db")).resolve(),
            storage_dir=Path(os.getenv("STORAGE_DIR", "storage")).resolve(),
            max_download_mb=max_download_mb,
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            mini_app_url=mini_app_url,
            mini_app_host=os.getenv("MINI_APP_HOST", "127.0.0.1"),
            mini_app_port=mini_app_port,
            admin_ids=admin_ids,
        )
