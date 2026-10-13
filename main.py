from __future__ import annotations

import asyncio
import logging
import time

from bot import ArchiveBot
from config import Settings
from database import Database
from miniapp import create_miniapp
import uvicorn


async def main() -> None:
    settings = Settings.from_env()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    database = Database(settings.database_path)
    await database.initialize()
    app = ArchiveBot(settings.bot_token, database, settings.storage_dir, settings.max_download_mb,
                     settings.mini_app_url, settings.admin_ids)
    web_server = uvicorn.Server(uvicorn.Config(
        create_miniapp(settings, database),
        host=settings.mini_app_host,
        port=settings.mini_app_port,
        log_level=settings.log_level.lower(),
        access_log=False,
    ))
    web_task = asyncio.create_task(web_server.serve(), name="miniapp-web-server")
    try:
        # Do not publish the Quick Tunnel URL in Telegram until the local Mini App
        # is actually serving requests. Otherwise the menu button can be tapped
        # during startup and Telegram may open an error page.
        deadline = time.monotonic() + 30
        while not web_server.started:
            if web_task.done():
                await web_task  # Propagate the original startup exception, if any.
                raise RuntimeError("Mini App server stopped before it became ready")
            if time.monotonic() >= deadline:
                raise TimeoutError("Mini App server did not become ready within 30 seconds")
            await asyncio.sleep(0.05)

        logging.getLogger(__name__).info(
            "Mini App ready at http://%s:%s", settings.mini_app_host, settings.mini_app_port
        )
        await app.run()
    finally:
        web_server.should_exit = True
        try:
            if not web_task.done():
                await web_task
        finally:
            await app.close()


if __name__ == "__main__":
    asyncio.run(main())
