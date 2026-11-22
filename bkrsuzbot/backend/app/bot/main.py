"""Запуск Telegram-бота (long polling): python -m app.bot.main"""

import asyncio
import logging
from datetime import timedelta

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.types import BotCommand, MenuButtonDefault, MenuButtonWebApp, WebAppInfo
from sqlalchemy import delete

from app.bot.handlers import router
from app.config import get_settings
from app.db import SessionLocal
from app.models import BotPayload, User
from app.services import userdata as ud
from app.services.container import Services

log = logging.getLogger(__name__)


class ContextMiddleware(BaseMiddleware):
    """Даёт обработчикам: session, svc, settings, user (из Telegram), is_new."""

    def __init__(self, svc: Services):
        self.svc = svc

    async def __call__(self, handler, event, data):
        tg_user = data.get("event_from_user")
        async with SessionLocal() as session:
            data["session"] = session
            data["svc"] = self.svc
            data["settings"] = self.svc.settings
            if tg_user:
                existing = await session.get(User, tg_user.id)
                data["is_new"] = existing is None
                data["user"] = await ud.get_user(session, tg_user.id, tg_user.first_name or "",
                                                 tg_user.language_code)
                await session.commit()
            return await handler(event, data)


async def cleanup_payloads() -> None:
    """Старые данные кнопок (старше 30 дней) больше не нужны."""
    while True:
        async with SessionLocal() as session:
            await session.execute(delete(BotPayload).where(
                BotPayload.created_at < ud.now() - timedelta(days=30)))
            await session.commit()
        await asyncio.sleep(24 * 3600)


async def setup_bot_profile(bot: Bot, webapp_url: str) -> None:
    for lang, cmds in {
        None: [("start", "Boshlash"), ("history", "Qidiruv tarixi"),
               ("favorites", "Saqlangan so‘zlar"), ("review", "Takrorlash"),
               ("settings", "Sozlamalar"), ("help", "Yordam")],
        "ru": [("start", "Начать"), ("history", "История поиска"),
               ("favorites", "Избранное"), ("review", "Повторение"),
               ("settings", "Настройки"), ("help", "Помощь")],
    }.items():
        await bot.set_my_commands([BotCommand(command=c, description=d) for c, d in cmds],
                                  language_code=lang)
    await bot.set_my_short_description(
        "Xitoy tili lug‘ati: ierogliflar, pinyin, tarjima, talaffuz. Китайский словарь.")
    await bot.set_my_description(
        "BKRSUZ — xitoy tili lug‘ati va tarjimon.\nSo‘z yoki matn yuboring: 鱼, baliq, yu2, рыба.\n\n"
        "Китайский словарь и переводчик для узбекоязычных и русскоязычных пользователей.")
    # Кнопка меню: Mini App, если задан WEBAPP_URL; иначе — обычное меню команд.
    await bot.set_chat_menu_button(menu_button=(
        MenuButtonWebApp(text="Lug‘at", web_app=WebAppInfo(url=webapp_url)) if webapp_url
        else MenuButtonDefault()))


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    if not settings.bot_token:
        raise SystemExit("BOT_TOKEN не задан")
    session = AiohttpSession(proxy=settings.proxy_url) if settings.proxy_url else None
    bot = Bot(settings.bot_token, session=session,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    svc = Services(settings)
    dp = Dispatcher()
    mw = ContextMiddleware(svc)
    dp.message.middleware(mw)
    dp.callback_query.middleware(mw)
    dp.inline_query.middleware(mw)
    dp.include_router(router)
    try:
        await setup_bot_profile(bot, settings.webapp_url)
        asyncio.create_task(cleanup_payloads())
        log.info("services configured: %s", svc.configured())
        await dp.start_polling(bot)
    except TelegramUnauthorizedError:
        raise SystemExit("BOT_TOKEN noto‘g‘ri (Telegram: Unauthorized). "
                         "@BotFather'dan tokenni qayta nusxalab .env ga yozing.") from None
    finally:
        await svc.aclose()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
