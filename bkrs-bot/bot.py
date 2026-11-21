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
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    LinkPreviewOptions,
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
    row = []
    # Кнопки web_app разрешены Telegram только в личных чатах.
    if private:
        row.append(InlineKeyboardButton(text="Открыть", web_app=WebAppInfo(url=bkrs_url(query))))
    row.append(InlineKeyboardButton(text="Браузер ↗", url=bkrs_url(query)))
    return InlineKeyboardMarkup(inline_keyboard=[row])


@dp.message(CommandStart())
async def start(message: Message) -> None:
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Открыть словарь", web_app=WebAppInfo(url=app_url()))
    ]])
    await message.answer(
        "<b>大БКРС</b>\n"
        "Китайско-русский словарь\n\n"
        "Отправьте слово — <i>你好</i>, <i>привет</i> или <i>nihao</i>.",
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
        f"<b>{escape(query)}</b>",
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
        title=text,
        description="Перевод в БКРС",
        input_message_content=InputTextMessageContent(
            message_text=f"<b>{escape(text)}</b>",
            link_preview_options=LinkPreviewOptions(is_disabled=True)),
        reply_markup=result_keyboard(text, private=False),
    )
    await query.answer([result], cache_time=60)


def escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def main() -> None:
    from aiogram.client.default import DefaultBotProperties
    from aiogram.client.session.aiohttp import AiohttpSession
    from aiogram.enums import ParseMode

    logging.basicConfig(level=logging.INFO)
    # Необязательный прокси (если Telegram заблокирован): http://, socks5://
    proxy = os.getenv("PROXY_URL", "").strip()
    session = AiohttpSession(proxy=proxy) if proxy else None
    bot = Bot(BOT_TOKEN, session=session,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    # Кнопка-меню «БКРС» слева от поля ввода открывает Mini App.
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(text="БКРС", web_app=WebAppInfo(url=app_url())))
    await bot.set_my_commands([BotCommand(command="start", description="Словарь")])
    await bot.set_my_short_description("Китайско-русский словарь БКРС")
    await bot.set_my_description(
        "大БКРС — китайско-русский словарь.\nОтправьте слово, и перевод откроется прямо в Telegram.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
