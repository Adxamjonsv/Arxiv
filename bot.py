from __future__ import annotations

import logging
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatType, UpdateType
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BusinessConnection, BusinessMessagesDeleted, BufferedInputFile, FSInputFile, InlineKeyboardButton,
    InlineKeyboardMarkup, MenuButtonWebApp, Message, Update, WebAppInfo,
)

from archive_service import ArchiveService, business_chat_title, safe_text
from database import Database
from onboarding import make_onboarding_image

logger = logging.getLogger(__name__)


class ArchiveBot:
    def __init__(self, token: str, db: Database, storage_dir: Path, max_download_mb: int,
                 mini_app_url: str = "", admin_ids: tuple[int, ...] = ()) -> None:
        self.db = db
        self.bot = Bot(token)
        self.dp = Dispatcher()
        self.router = Router()
        self.service = ArchiveService(self.bot, db, storage_dir, max_download_mb)
        self.mini_app_url = mini_app_url
        self.admin_ids = frozenset(admin_ids)
        self.dp.include_router(self.router)

        self.router.message.register(self.start, CommandStart())
        self.router.message.register(self.status, Command("status"))
        self.router.message.register(self.pause, Command("pause"))
        self.router.message.register(self.resume, Command("resume"))
        self.router.message.register(self.help, Command("help"))
        self.router.message.register(self.admin, Command("admin"))
        self.router.business_connection.register(self.on_connection)
        self.router.business_message.register(self.on_business_message)
        self.router.edited_business_message.register(self.on_business_edit)
        self.dp.update.register(self.on_deleted_update, F.deleted_business_messages)

    async def language(self, message: Message) -> str:
        if message.from_user:
            saved = await self.db.language_for_owner(message.from_user.id)
            if saved in {"uz", "ru"}:
                return saved
        code = (message.from_user.language_code if message.from_user else None) or "uz"
        return "ru" if code.lower().startswith("ru") else "uz"

    async def start(self, message: Message) -> None:
        if message.chat.type != ChatType.PRIVATE:
            return
        ru = (await self.language(message)) == "ru"
        text = ("Здравствуйте! Это архив ваших чатов Telegram Business.\n\n"
                "1. Откройте Настройки Telegram → Business → Chat Automation.\n"
                "2. Выберите этого бота и разрешите доступ только к нужным чатам.\n"
                "3. Вернитесь сюда и отправьте /resume.\n\n"
                "Откройте Мини-приложение кнопкой «Архив» в меню этого чата. /help — сведения о данных и ограничениях."
                if ru else
                "Assalomu alaykum! Bu Telegram Business chatlaringiz arxivi.\n\n"
                "1. Telegram Sozlamalari → Business → Chat Automation’ni oching.\n"
                "2. Shu botni tanlab, faqat kerakli chatlarga ruxsat bering.\n"
                "3. Bu chatga qaytib /resume yuboring.\n\n"
                "Mini App’ni chat menyusidagi «Arxiv» tugmasidan oching. /help — ma’lumot va cheklovlar.")
        if message.from_user and message.from_user.id in self.admin_ids:
            text += "\n/admin — admin panel" if not ru else "\n/admin — панель администратора"
        try:
            guide_path = Path(__file__).resolve().parent / "Инструкция подключения @chat_file_save_bot за 3 шага.png"
            photo = (FSInputFile(guide_path) if ru and guide_path.is_file()
                     else make_onboarding_image("ru" if ru else "uz"))
            await message.answer_photo(photo=photo, caption=text)
        except Exception:
            logger.exception("Could not send onboarding guide image")
            await message.answer(text)

    async def help(self, message: Message) -> None:
        if (await self.language(message)) == "ru":
            text = ("Бот сохраняет обычные сообщения и поддерживаемые медиа, которые Telegram доставляет "
                    "через подключение Business. Изменения и уведомления об удалении записываются; "
                    "бот может отправить ранее сохранённую копию удалённого медиа в этот чат. "
                    "Telegram не возвращает содержимое, если оно не было получено заранее. "
                    "Медиа с таймером и защищённый контент не обходятся. /pause останавливает архивирование; "
                    "отключите бота в настройках Business, чтобы отозвать доступ.")
        else:
            text = ("Bot Telegram Business ulanishi orqali kelgan oddiy xabarlar va qo‘llab-quvvatlanadigan "
                    "medialarni saqlaydi. Tahrir va o‘chirishlar qayd qilinadi; oldin saqlangan o‘chirilgan "
                    "media nusxasi shu chatga yuborilishi mumkin. Telegram oldindan olinmagan xabarni "
                    "qaytarmaydi. Vaqtli va himoyalangan media chetlab o‘tilmaydi. /pause arxivni to‘xtatadi; "
                    "ruxsatni bekor qilish uchun Business sozlamasidan botni uzing.")
        await message.answer(text)

    async def admin(self, message: Message) -> None:
        if message.chat.type != ChatType.PRIVATE:
            return
        if not message.from_user or message.from_user.id not in self.admin_ids:
            await message.answer("Эта команда доступна только администратору." if (await self.language(message)) == "ru"
                                 else "Bu buyruq faqat bot administratoriga ochiq.")
            return
        if not self.mini_app_url:
            await message.answer("Для панели администратора не настроен HTTPS Mini App. Запустите start.py." if (await self.language(message)) == "ru"
                                 else "Admin panel uchun HTTPS Mini App manzili sozlanmagan. start.py orqali ishga tushiring.")
            return
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Admin panelini ochish", web_app=WebAppInfo(url=self.mini_app_url))
        ]])
        panel_text = ("Панель администратора: статистика, пользователи и архивы подключённых Business-аккаунтов."
                      if (await self.language(message)) == "ru" else
                      "Admin panel: statistikalar, foydalanuvchilar va ruxsat bilan ulangan Business arxivlari.")
        await message.answer(panel_text, reply_markup=keyboard)

    async def status(self, message: Message) -> None:
        conns = await self.db.connections_for_owner(message.from_user.id)
        ru = (await self.language(message)) == "ru"
        if not conns:
            await message.answer("Подключите бота в настройках Telegram Business." if ru else
                                 "Telegram Business sozlamalaridan botni ulang.")
            return
        enabled = any(row["enabled"] for row in conns)
        if ru:
            await message.answer(f"Подключений Business: {len(conns)}\nАрхив: {'включён' if enabled else 'приостановлен'}")
        else:
            await message.answer(f"Business ulanishlari: {len(conns)}\nArxiv: {'yoqilgan' if enabled else 'to‘xtatilgan'}")

    async def pause(self, message: Message) -> None:
        await self.db.set_owner_enabled(message.from_user.id, False)
        await message.answer("Архив приостановлен. Отправьте /resume, чтобы включить." if (await self.language(message)) == "ru"
                             else "Arxiv to‘xtatildi. Qayta yoqish uchun /resume yuboring.")

    async def resume(self, message: Message) -> None:
        rows = await self.db.connections_for_owner(message.from_user.id)
        if not rows:
            await message.answer("Сначала подключите бота в настройках Telegram Business." if (await self.language(message)) == "ru"
                                 else "Avval botni Telegram Business sozlamalaridan ulang.")
            return
        await self.db.set_owner_enabled(message.from_user.id, True)
        await message.answer("Архивирование включено для активных подключений Business." if (await self.language(message)) == "ru"
                             else "Faol Business ulanishlaringiz uchun arxiv yoqildi.")

    async def on_connection(self, connection: BusinessConnection) -> None:
        previous = await self.db.connection(connection.id)
        opted_in = bool(previous and previous["enabled"] and connection.is_enabled)
        await self.db.save_connection(
            connection_id=connection.id,
            owner_id=connection.user.id,
            notify_chat_id=connection.user_chat_id,
            enabled=opted_in,
            owner_name=" ".join(part for part in (connection.user.first_name, connection.user.last_name) if part),
            owner_username=connection.user.username,
        )
        logger.info("Business connection updated owner_id=%s enabled=%s", connection.user.id, connection.is_enabled)
        if not connection.is_enabled:
            return
        try:
            saved_language = await self.db.language_for_owner(connection.user.id)
            language_code = saved_language or (connection.user.language_code or "uz")
            ru = language_code.lower().startswith("ru")
            if ru:
                notice = ("Подключение Business обновлено. Архивирование активно." if opted_in else
                          "Подключение Business получено. Архив остановлен: отправьте /resume, чтобы включить.")
                notice += " Используйте /help для информации о данных и ограничениях."
            else:
                notice = ("Business ulanishi yangilandi. Arxiv faol." if opted_in else
                          "Business ulanishi qabul qilindi. Arxivni yoqish uchun /resume yuboring.")
                notice += " Ma’lumot va cheklovlar uchun /help yuboring."
            await self.bot.send_message(
                connection.user_chat_id,
                notice,
            )
        except Exception:
            logger.exception("Could not notify Business connection owner")

    async def _context(self, message: Message) -> dict | None:
        if not message.business_connection_id:
            return None
        connection = await self.db.connection(message.business_connection_id)
        if not connection or not connection["enabled"]:
            return None
        return connection

    async def on_business_message(self, message: Message) -> None:
        context = await self._context(message)
        if context is None:
            return
        await self.service.capture(message, context["owner_id"], context["connection_id"])

    async def on_business_edit(self, message: Message) -> None:
        context = await self._context(message)
        if context is None:
            return
        old = await self.db.message(context["connection_id"], message.chat.id, message.message_id)
        previous = old["text"] if old else None
        title = business_chat_title(message.chat, message.chat.id)
        # Telegram sends the full edited Business message, including replacement
        # media. Cache that current version even if only the media changed and
        # the caption/text stayed identical. Keep `previous` from the DB first,
        # because capture() updates the baseline row to the current version.
        await self.service.capture(message, context["owner_id"], context["connection_id"])
        if old is not None:
            await self.db.set_chat_title(context["connection_id"], message.chat.id, message.message_id, title)
        author = " ".join(part for part in
                          ((message.from_user.first_name if message.from_user else None),
                           (message.from_user.last_name if message.from_user else None)) if part) or title
        author_username = message.from_user.username if message.from_user else None
        updated = message.text or message.caption
        if previous == updated:
            return
        await self.db.edit(context["connection_id"], message.chat.id, message.message_id,
                           previous, updated, title, author, author_username)
        ru = await self.db.language_for_owner(context["owner_id"]) == "ru"
        if ru:
            notice = (f"Сообщение изменено · {safe_text(author, 120)}\nЧат: {safe_text(title, 120)}\n\n"
                      f"До:\n{safe_text(previous, 1500)}\n\nПосле:\n{safe_text(updated, 1500)}")
        else:
            notice = (f"Xabar tahrirlandi · {safe_text(author, 120)}\nChat: {safe_text(title, 120)}\n\n"
                      f"Oldin:\n{safe_text(previous, 1500)}\n\nKeyin:\n{safe_text(updated, 1500)}")
        await self.bot.send_message(context["notify_chat_id"], notice)

    async def on_deleted_update(self, update: Update) -> None:
        deleted: BusinessMessagesDeleted | None = update.deleted_business_messages
        if deleted is None:
            return
        context = await self.db.connection(deleted.business_connection_id)
        if not context or not context["enabled"]:
            return
        for message_id in deleted.message_ids:
            await self.db.set_chat_title(
                deleted.business_connection_id, deleted.chat.id, message_id,
                business_chat_title(deleted.chat, deleted.chat.id),
            )
            old = await self.db.deleted(
                deleted.business_connection_id, deleted.chat.id, message_id,
                owner_id=context["owner_id"],
                chat_title=business_chat_title(deleted.chat, deleted.chat.id),
            )
            if not old:
                continue
            file_path = old.get("file_path")
            media_type = old.get("media_type")
            author = old.get("sender_name") or (f"@{old['sender_username']}" if old.get("sender_username") else old.get("chat_title"))
            archived_text = safe_text(old.get("text"), 1800)
            media_saved = bool(file_path and Path(file_path).is_file())
            ru = await self.db.language_for_owner(context["owner_id"]) == "ru"

            if ru:
                labels = {"photo": "Фото", "video": "Видео", "voice": "Голосовое сообщение", "video_note": "Видеосообщение"}
                label = labels.get(media_type, "Медиа")
                text = (f"🗑 Сообщение удалено · {safe_text(author, 120)}\n"
                        f"Чат: {safe_text(old.get('chat_title'), 120)}\nТекст: {archived_text}")
            else:
                labels = {"photo": "Rasm", "video": "Video", "voice": "Ovozli xabar", "video_note": "Dumaloq video"}
                label = labels.get(media_type, "Media")
                text = (f"🗑 Xabar o‘chirildi · {safe_text(author, 120)}\n"
                        f"Chat: {safe_text(old.get('chat_title'), 120)}\nXabar: {archived_text}")

            if media_type:
                media_state = (" (сохранено)" if media_saved else " (копия файла не сохранена)") if ru else (" (saqlandi)" if media_saved else " (fayl nusxasi olinmagan)")
                text += f"\nМедиа: {label}{media_state}" if ru else f"\nMedia: {label}{media_state}"

            await self.bot.send_message(context["notify_chat_id"], text)

            if media_saved:
                try:
                    media_file = FSInputFile(file_path)
                    if media_type == "photo":
                        await self.bot.send_photo(context["notify_chat_id"], media_file)
                    elif media_type == "video":
                        await self.bot.send_video(context["notify_chat_id"], media_file)
                    elif media_type == "voice":
                        await self.bot.send_voice(context["notify_chat_id"], media_file)
                    elif media_type == "video_note":
                        await self.bot.send_video_note(context["notify_chat_id"], media_file)
                    else:
                        await self.bot.send_document(context["notify_chat_id"], media_file)
                except Exception:
                    logger.exception("Could not deliver deleted media owner=%s message=%s", context["owner_id"], message_id)
                    try:
                        await self.bot.send_document(context["notify_chat_id"], FSInputFile(file_path))
                    except Exception:
                        logger.exception("Could not send deleted media as document owner=%s message=%s", context["owner_id"], message_id)

    async def run(self) -> None:
        if self.mini_app_url:
            await self.bot.set_chat_menu_button(menu_button=MenuButtonWebApp(
                text="Arxiv", web_app=WebAppInfo(url=self.mini_app_url)
            ))
        await self.dp.start_polling(self.bot, allowed_updates=[
            UpdateType.MESSAGE, UpdateType.BUSINESS_CONNECTION, UpdateType.BUSINESS_MESSAGE,
            UpdateType.EDITED_BUSINESS_MESSAGE, UpdateType.DELETED_BUSINESS_MESSAGES,
        ])

    async def close(self) -> None:
        await self.bot.session.close()
