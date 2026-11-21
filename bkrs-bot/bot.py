"""Telegram-бот + Mini App для словаря БКРС (bkrs.info).

Любое слово (китайское, русское, пиньинь), отправленное боту, открывается
как страница bkrs.info прямо внутри Telegram (Mini App). Пользователь видит
ровно то, что показывает сайт: переводы, примеры, иероглифику, ссылки.
"""

import asyncio
import logging
import os
from urllib.parse import quote, urlencode

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()
BKRS_BASE = "https://bkrs.info"
MAX_QUERY_LEN = 200

dp = Dispatcher()


def bkrs_url(query: str) -> str:
    """Ссылка на страницу bkrs.info с результатами поиска."""
    return f"{BKRS_BASE}/slovo.php?ch={quote(query.strip(), safe='')}"


def app_url(query: str | None = None) -> str:
    """URL для Mini App: наша обёртка (если задана) или сам bkrs.info."""
    if WEBAPP_URL:
        if not query:
            return WEBAPP_URL
        sep = "&" if "?" in WEBAPP_URL else "?"
        return f"{WEBAPP_URL}{sep}{urlencode({'q': query})}"
    return bkrs_url(query) if query else BKRS_BASE + "/"


def result_keyboard(query: str, private: bool = True) -> InlineKeyboardMarkup:
    rows = []
    # Кнопки web_app разрешены Telegram только в личных чатах.
    if private:
        rows.append([InlineKeyboardButton(
            text=f"🔎 «{query[:40]}» в БКРС", web_app=WebAppInfo(url=bkrs_url(query)))])
    rows.append([InlineKeyboardButton(text="🌐 Открыть в браузере", url=bkrs_url(query))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.message(CommandStart())
async def start(message: Message) -> None:
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📖 Открыть БКРС", web_app=WebAppInfo(url=app_url()))
    ]])
    await message.answer(
        "大БКРС — большой китайско-русский словарь.\n\n"
        "Отправьте слово на китайском, русском или пиньинем — "
        "я открою результат с сайта bkrs.info прямо в Telegram.\n\n"
        "Также можно нажать кнопку «БКРС» внизу слева или использовать меня "
        "в любом чате: <code>@имя_бота слово</code>.",
        reply_markup=kb,
    )


@dp.message(Command("help"))
async def help_cmd(message: Message) -> None:
    await start(message)


@dp.message(F.text & ~F.text.startswith("/"))
async def search(message: Message) -> None:
    query = message.text.strip()[:MAX_QUERY_LEN]
    if not query:
        return
    private = message.chat.type == ChatType.PRIVATE
    await message.answer(
        f"Поиск в БКРС: <b>{escape(query)}</b>",
        reply_markup=result_keyboard(query, private),
    )


@dp.inline_query()
async def inline(query: InlineQuery) -> None:
    text = query.query.strip()[:MAX_QUERY_LEN]
    if not text:
        await query.answer([], cache_time=5)
        return
    result = InlineQueryResultArticle(
        id="bkrs",
        title=f"БКРС: {text}",
        description="Открыть перевод на bkrs.info",
        input_message_content=InputTextMessageContent(
            message_text=f"Поиск в БКРС: <b>{escape(text)}</b>\n{bkrs_url(text)}"),
        reply_markup=result_keyboard(text, private=False),
    )
    await query.answer([result], cache_time=60)


def escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def main() -> None:
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    logging.basicConfig(level=logging.INFO)
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    # Кнопка-меню «БКРС» слева от поля ввода открывает Mini App.
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(text="БКРС", web_app=WebAppInfo(url=app_url())))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
