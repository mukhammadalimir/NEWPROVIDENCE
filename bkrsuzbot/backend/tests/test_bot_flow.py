"""Сценарии бота: обновления Telegram подаются в диспетчер aiogram,
а запросы к Bot API перехватываются (сеть не используется)."""

import itertools
from datetime import datetime, timezone

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import (
    AnswerCallbackQuery,
    AnswerInlineQuery,
    EditMessageReplyMarkup,
    EditMessageText,
    SendMessage,
    SendVoice,
)
from aiogram.types import CallbackQuery, Chat, InlineQuery, Message, Update, User

from app.bot.handlers import router
from app.bot.main import ContextMiddleware

ids = itertools.count(1)


class RecordingSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        chat = Chat(id=getattr(method, "chat_id", 1) or 1, type="private")
        if isinstance(method, (SendMessage, SendVoice, EditMessageText, EditMessageReplyMarkup)):
            return Message(message_id=next(ids), date=datetime.now(timezone.utc), chat=chat,
                           text=getattr(method, "text", None), reply_markup=getattr(method, "reply_markup", None))
        return True

    async def stream_content(self, *a, **kw):  # pragma: no cover
        raise NotImplementedError

    async def close(self):
        pass

    def sent(self, kind=SendMessage):
        return [c for c in self.calls if isinstance(c, kind)]


@pytest.fixture
def harness(make_services):
    def build(**overrides):
        svc = make_services(**overrides)
        dp = Dispatcher()
        mw = ContextMiddleware(svc)
        dp.message.middleware(mw)
        dp.callback_query.middleware(mw)
        dp.inline_query.middleware(mw)
        router._parent_router = None  # роутер можно подключить к новому диспетчеру
        dp.include_router(router)
        rec = RecordingSession()
        bot = Bot("123456:TEST-TOKEN", session=rec)
        return dp, bot, rec
    return build


def msg(uid, text):
    u = User(id=uid, is_bot=False, first_name="T", language_code="uz")
    return Update(update_id=next(ids), message=Message(
        message_id=next(ids), date=datetime.now(timezone.utc),
        chat=Chat(id=uid, type="private"), from_user=u, text=text))


def cb(uid, data, message_markup=None):
    u = User(id=uid, is_bot=False, first_name="T")
    m = Message(message_id=next(ids), date=datetime.now(timezone.utc),
                chat=Chat(id=uid, type="private"), text="x", reply_markup=message_markup)
    return Update(update_id=next(ids), callback_query=CallbackQuery(
        id=str(next(ids)), from_user=u, chat_instance="ci", data=data, message=m))


def buttons(method):
    return [b for row in method.reply_markup.inline_keyboard for b in row]


async def test_start_and_language(harness):
    dp, bot, rec = harness()
    await dp.feed_update(bot, msg(3001, "/start"))
    first = rec.sent()[-1]
    assert [b.callback_data for b in buttons(first)] == ["ui:uz", "ui:ru"]
    await dp.feed_update(bot, cb(3001, "ui:ru"))
    assert "китайский словарь" in rec.sent(EditMessageText)[-1].text


async def test_word_card_audio_and_favorite(harness):
    dp, bot, rec = harness()
    await dp.feed_update(bot, msg(3002, "baliq"))
    card = rec.sent()[-1]
    assert "<b>鱼</b>" in card.text and "yú" in card.text and "baliq" in card.text
    btns = {b.text: b for b in buttons(card)}
    audio = next(b for t, b in btns.items() if t.startswith("🔊 鱼"))
    slow = next(b for t, b in btns.items() if t.startswith("🐢"))
    fav = next(b for t, b in btns.items() if t.startswith("⭐"))
    assert any(t.startswith("⚠️") for t in btns)

    # Озвучка приходит голосовым сообщением (OGG)
    await dp.feed_update(bot, cb(3002, audio.callback_data))
    voice = rec.sent(SendVoice)[-1]
    assert voice.caption == "鱼"
    await dp.feed_update(bot, cb(3002, slow.callback_data))
    assert len(rec.sent(SendVoice)) == 2

    # Избранное: добавить и убрать
    from app.db import SessionLocal
    from app.services import userdata as ud
    await dp.feed_update(bot, cb(3002, fav.callback_data, card.reply_markup))
    async with SessionLocal() as s:
        assert [f["headword"] for f in await ud.list_favorites(s, 3002)] == ["鱼"]
    await dp.feed_update(bot, cb(3002, fav.callback_data, card.reply_markup))
    async with SessionLocal() as s:
        assert await ud.list_favorites(s, 3002) == []


async def test_ambiguous_then_pinyin(harness):
    dp, bot, rec = harness(google_api_key="")
    await dp.feed_update(bot, msg(3003, "yu"))
    ask = rec.sent()[-1]
    labels = [b.text for b in buttons(ask)]
    assert labels == ["Pinyin (xitoycha o‘qilishi)", "O‘zbekcha"]
    await dp.feed_update(bot, cb(3003, buttons(ask)[0].callback_data))
    cands = rec.sent()[-1]
    assert buttons(cands)[0].text.startswith("鱼")
    # без ключа TTS кнопок озвучки нет
    await dp.feed_update(bot, cb(3003, buttons(cands)[0].callback_data))
    assert not any(b.text.startswith("🔊") for b in buttons(rec.sent()[-1]))


async def test_tts_not_configured_alert(harness):
    dp, bot, rec = harness(google_api_key="")
    from app.db import SessionLocal
    from app.services import userdata as ud
    async with SessionLocal() as s:
        await ud.get_user(s, 3004)
        pid = await ud.put_payload(s, {"text": "鱼"})
        await s.commit()
    await dp.feed_update(bot, cb(3004, f"a:{pid}:0"))
    alert = rec.sent(AnswerCallbackQuery)[-1]
    assert alert.show_alert and "ulanmagan" in alert.text


async def test_sentence_translation_message(harness):
    dp, bot, rec = harness()
    await dp.feed_update(bot, msg(3005, "我喜欢吃鱼。"))
    m = rec.sent()[-1]
    assert "Men baliq yeyishni yaxshi ko‘raman." in m.text and "wǒ" in m.text
    assert "mashina tarjimasi" in m.text
    assert any(b.copy_text for b in buttons(m))


async def test_report_reaches_admin_only(harness):
    dp, bot, rec = harness()
    await dp.feed_update(bot, msg(3006, "baliq"))
    report_btn = next(b for b in buttons(rec.sent()[-1]) if b.text.startswith("⚠️"))
    await dp.feed_update(bot, cb(3006, report_btn.callback_data))
    await dp.feed_update(bot, msg(3006, "misol noto‘g‘ri"))
    texts = [(c.chat_id, c.text) for c in rec.sent()]
    assert any(cid == 1000 and "misol noto‘g‘ri" in t for cid, t in texts)  # ADMIN_IDS=1000
    assert any(cid == 3006 and "Rahmat" in t for cid, t in texts)


async def test_admin_commands_protected(harness):
    dp, bot, rec = harness()
    n = len(rec.calls)
    await dp.feed_update(bot, msg(3007, "/admin"))
    assert len(rec.calls) == n  # не админ — нет ответа
    await dp.feed_update(bot, msg(1000, "/admin"))
    assert "Admin" in rec.sent()[-1].text


async def test_inline_share(harness):
    dp, bot, rec = harness(google_api_key="")
    u = User(id=3008, is_bot=False, first_name="T")
    await dp.feed_update(bot, Update(update_id=next(ids), inline_query=InlineQuery(
        id="iq", from_user=u, query="鱼", offset="")))
    ans = [c for c in rec.calls if isinstance(c, AnswerInlineQuery)][-1]
    assert ans.results and ans.results[0].title.startswith("鱼")


async def test_delete_data(harness):
    dp, bot, rec = harness(google_api_key="")
    await dp.feed_update(bot, msg(3009, "鱼"))
    await dp.feed_update(bot, cb(3009, "del:yes"))
    from app.db import SessionLocal
    from app.models import User as DbUser
    async with SessionLocal() as s:
        assert await s.get(DbUser, 3009) is None
