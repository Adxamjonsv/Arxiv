# Telegram Business Archive

An opt-in Telegram Business archiver using the official Bot API through aiogram. It does not log in as a user or collect Telegram login codes, passwords, or session files.

## Setup

1. Create a bot with BotFather and enable Business Mode for it.
2. Copy `.env.example` to `.env`, then set your `BOT_TOKEN` there.
3. Add your Telegram numeric user ID to `ADMIN_IDS` in `.env` (multiple IDs can be comma-separated).
4. In PyCharm, run `start.py`. It installs missing packages, opens a temporary HTTPS Quick Tunnel, and starts the bot and Mini App.
5. Start a private chat with the bot, connect it in Telegram Settings → Business → Chat Automation, then send `/resume` to opt in. Open the Mini App from the bot chat's “Arxiv” menu button.

### One-click start from PyCharm

Set PyCharm's Python interpreter to a working Python 3.11+ environment, then run `start.py` instead of `main.py`. The launcher installs missing Python requirements, downloads Cloudflare's official Windows x64 `cloudflared` release and verifies its SHA-256, opens a temporary HTTPS Quick Tunnel to the local Mini App, passes the generated URL to the bot, and runs the bot and Mini App together. The first launch needs internet access. Keep the Run window open; pressing Stop closes the tunnel as well. Quick Tunnel URLs change each run and are intended for development/testing, not a permanent production URL.

To run `main.py` directly, provide a stable public HTTPS URL through `MINI_APP_URL`; the automatic Quick Tunnel behavior is in `start.py`.

### Deploy to Railway

Railway uses the included Linux `Dockerfile` and starts `main.py` directly. Do not use `start.py` on Railway; that launcher is for Windows/PyCharm and starts a local Cloudflare Quick Tunnel. In Railway, add `BOT_TOKEN` as a service variable, generate a public domain under **Settings → Networking**, and set `ADMIN_IDS` to your own Telegram numeric ID if you need the admin panel. The app automatically uses Railway's `RAILWAY_PUBLIC_DOMAIN` for its Mini App URL and listens on Railway's `PORT`.

For persistent archives, attach a Railway Volume mounted at `/data`, then set `DATABASE_PATH=/data/archive.db` and `STORAGE_DIR=/data/storage` in service variables. Keep the service at one replica because this version uses SQLite and local files. Configure `/health` as the Railway healthcheck path if desired. Never commit `.env` or paste `BOT_TOKEN` into GitHub or chat.

The Business account must grant the message access required by Telegram. The bot only receives the chats and update types permitted by the connection and Telegram's Bot API.

## Commands

- `/status` — show active connection count and archive state.
- `/resume` — opt in to archiving for active connections.
- `/pause` — stop new message archiving.
- `/help` — describe storage and limits.
- `/admin` — open the admin Mini App (only for IDs in `ADMIN_IDS`).

`/start` sends a setup guide image and localized instructions. The language follows the Telegram user's language (`ru` for Russian, Uzbek otherwise). When an archived photo/video/voice/video-note is later deleted, the bot sends the media directly into the owner's private bot chat; the Mini App does not need to be open. The bot first tries the native Telegram media message type and falls back to a document if Telegram rejects that format.

## Data and privacy

For each connected owner, the service stores all delivered text/captions and supported ordinary photos, videos, voice messages, and video notes under `storage/{business_owner_telegram_id}/{chat_id}/`. The Mini App shows the owner's own chats and messages in chat order, including edits with before/after text and deletion markers. The bot sends private notifications for edits and deletions; when a deleted media file was successfully cached, it also sends that file. Use `/pause` to stop archiving and disconnect the bot in Business settings to revoke its access.

Configure `DATABASE_PATH`, `STORAGE_DIR`, `MAX_DOWNLOAD_MB` (1–20 MB with the standard Telegram Bot API), `LOG_LEVEL`, and `MINI_APP_HOST` / `MINI_APP_PORT` in `.env` as needed. Keep the host and backups access-controlled; this archive contains private messages and media.

The Mini App validates Telegram `initData` with the bot token and scopes ordinary user queries to the authenticated Telegram user. Admin endpoints require an `ADMIN_IDS` match; admins can select a connected account and inspect its chat list, messages, edits, and locally stored media, as well as pause its archiving. Chat labels use the title, first/last name, or username provided in Telegram updates. The Bot API does not provide a separate phone contact-alias field, so a custom address-book name cannot be guaranteed.

## Telegram limitations

The bot archives only updates Telegram delivers after the connection is active. It cannot recover history it did not receive. An edit update can be compared with a locally stored earlier version. A deletion update includes message IDs, not the deleted content; the original can be shown only when it arrived and was stored earlier. Standard Telegram Bot API file downloads are limited to 20 MB, and protected media is not downloaded. View-once or self-destructing media is not extracted or bypassed. The service does not use Telethon or a logged-in user account.
