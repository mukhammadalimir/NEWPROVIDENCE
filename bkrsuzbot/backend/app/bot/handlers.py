"""Обработчики Telegram-бота."""

import logging
from html import escape
from urllib.parse import urlencode

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    CopyTextButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    Message,
    WebAppInfo,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import render
from app.bot.i18n import t
from app.config import Settings
from app.models import DictEntry, ErrorReport, FeatureFlag, User
from app.services import dictionary as dic
from app.services import userdata as ud
from app.services.ai import AIUnavailable
from app.services.container import FLAG_DEFAULTS, Services
from app.services.events import log_event
from app.services.search import search
from app.services.tts import TTSUnavailable
from app.text import pinyin as py

log = logging.getLogger(__name__)
router = Router()

SRC_KEYS = {"pinyin": "src_pinyin", "uz": "src_uz", "ru": "src_ru", "zh": "src_zh"}


class ReportState(StatesGroup):
    waiting = State()


Btn = InlineKeyboardButton


def kb(rows: list[list[Btn]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[r for r in rows if r])


def webapp_button(settings: Settings, text: str, query: str | None = None) -> Btn | None:
    if not settings.webapp_url:
        return None
    url = settings.webapp_url
    if query:
        url += ("&" if "?" in url else "?") + urlencode({"q": query})
    return Btn(text=text, web_app=WebAppInfo(url=url))


# ---------- /start, язык, помощь ----------

def lang_keyboard() -> InlineKeyboardMarkup:
    return kb([[Btn(text="🇺🇿 O‘zbekcha", callback_data="ui:uz"),
                Btn(text="🇷🇺 Русский", callback_data="ui:ru")]])


@router.message(CommandStart())
async def start(message: Message, session: AsyncSession, user: User, is_new: bool,
                settings: Settings, state: FSMContext):
    await state.clear()
    if is_new:
        await message.answer(t("uz", "choose_ui"), reply_markup=lang_keyboard())
        return
    await send_welcome(message, user.ui_lang, settings)


async def send_welcome(message: Message, ui: str, settings: Settings):
    btn = webapp_button(settings, t(ui, "open_app"))
    await message.answer(t(ui, "welcome") + "\n\n" + t(ui, "help"),
                         reply_markup=kb([[btn]]) if btn else None)


@router.callback_query(F.data.startswith("ui:"))
async def set_ui(cb: CallbackQuery, session: AsyncSession, user: User, settings: Settings):
    lang = cb.data.split(":")[1]
    await ud.update_settings(session, user, ui_lang=lang, target_lang=lang)
    await cb.message.edit_text(t(lang, "welcome"))
    btn = webapp_button(settings, t(lang, "open_app"))
    await cb.message.answer(t(lang, "help"), reply_markup=kb([[btn]]) if btn else None)
    await cb.answer()


@router.message(Command("help"))
async def help_cmd(message: Message, user: User, settings: Settings):
    await send_welcome(message, user.ui_lang, settings)


@router.message(Command("cancel"))
async def cancel(message: Message, user: User, state: FSMContext):
    await state.clear()
    await message.answer(t(user.ui_lang, "cancelled"))


# ---------- Поиск ----------

async def run_search(message: Message, session: AsyncSession, svc: Services, user: User,
                     settings: Settings, query: str, source: str | None = None,
                     target: str | None = None):
    ui = user.ui_lang
    if not svc.search_limiter.allow(user.id):
        await message.answer(t(ui, "rate_limited"))
        return
    result = await search(session, svc, query, user_target=user.target_lang, source=source,
                          target=target)
    rtype = result["type"]
    q = result["query"]

    if rtype in ("word", "candidates", "text"):
        await ud.add_history(session, user.id, q, rtype)
        await session.commit()

    if rtype == "choose":
        rows = []
        for opt in result["options"]:
            pid = await ud.put_payload(session, {"q": q, "src": opt})
            rows.append([Btn(text=t(ui, SRC_KEYS[opt]), callback_data=f"s:{pid}")])
        await session.commit()
        await message.answer(t(ui, "choose_dir", q=escape(q)), reply_markup=kb(rows))
        return

    alt_rows = []
    for alt in result.get("alternatives", []):
        pid = await ud.put_payload(session, {"q": q, "src": alt})
        alt_rows.append([Btn(text=t(ui, "search_as", lang=t(ui, SRC_KEYS[alt])),
                             callback_data=f"s:{pid}")])

    notice = render.notices_text(result, ui)
    if rtype == "not_found":
        await session.commit()
        await message.answer(t(ui, "not_found", q=escape(q)) + ("\n\n" + notice if notice else ""),
                             reply_markup=kb(alt_rows) if alt_rows else None)
        return

    if rtype == "candidates":
        rows = []
        # значения в выбранной карточке — на языке запроса (ru/uz)
        mlang = result.get("source_lang") if result.get("source_lang") in ("uz", "ru") else ""
        for c in result["candidates"][:12]:
            label = f"{c['headword']}  {c['pinyin']}  {c['gloss']}"[:60]
            rows.append([Btn(text=label, callback_data=f"e:{c['entry_id']}:{mlang}")])
        await session.commit()
        await message.answer(t(ui, "candidates", q=escape(q)), reply_markup=kb(rows + alt_rows))
        return

    if rtype == "text":
        tx = result["text"]
        rows = []
        if (await svc.available(session))["tts"]:
            pid = await ud.put_payload(session, {"text": tx["zh"][:300]})
            rows.append([Btn(text=t(ui, "btn_listen_sentence"), callback_data=f"a:{pid}:0"),
                         Btn(text=t(ui, "btn_slow"), callback_data=f"a:{pid}:1")])
        copy = tx["translation"] or tx["zh"]
        rows.append([Btn(text=t(ui, "btn_copy"), copy_text=CopyTextButton(text=copy[:256]))])
        rpid = await ud.put_payload(session, {"q": q})
        rows.append([Btn(text=t(ui, "btn_report"), callback_data=f"r:{rpid}")])
        await session.commit()
        body = render.text_result(result, ui) + ("\n\n" + notice if notice else "")
        await message.answer(body, reply_markup=kb(rows + alt_rows))
        return

    # Карточки слова
    lang = render.meaning_lang(result)
    if notice:
        await message.answer(notice)
    for card in result["cards"][:3]:
        markup = await card_keyboard(session, svc, settings, user, card, q, lang)
        await session.commit()
        await message.answer(render.card_text(card, ui, lang), reply_markup=kb(markup + alt_rows))


async def card_keyboard(session: AsyncSession, svc: Services, settings: Settings, user: User,
                        card: dict, query: str, lang: str) -> list[list[Btn]]:
    ui = user.ui_lang
    avail = await svc.available(session)
    rows: list[list[Btn]] = []
    multi = len(card["readings"]) > 1
    for r in card["readings"][:4]:
        label = r["pinyin"] if multi else card["headword"]
        row = []
        if avail["tts"]:
            pid = await ud.put_payload(session, {"text": card["headword"]})
            row += [Btn(text=t(ui, "btn_listen", w=label), callback_data=f"a:{pid}:0"),
                    Btn(text=t(ui, "btn_slow"), callback_data=f"a:{pid}:1")]
        gloss = ", ".join(r["senses"][0]["items"]) if r["senses"] else (
            "; ".join((r.get("english_mt") or r["english"])[:2]))
        fav = await ud.find_favorite(session, user.id, card["headword"], r["pinyin"])
        fpid = await ud.put_payload(session, {"h": card["headword"], "p": r["pinyin"],
                                              "g": gloss, "e": r["entry_id"]})
        w = r["pinyin"] if multi else ""
        row.append(Btn(text=t(ui, "btn_saved" if fav else "btn_save", w=w).strip(),
                       callback_data=f"f:{fpid}"))
        rows.append(row)
        if avail["tts"] and r["examples"]:
            pid = await ud.put_payload(session, {"text": r["examples"][0]["zh"]})
            rows.append([Btn(text=t(ui, "btn_listen_sentence") + (f" ({r['pinyin']})" if multi else ""),
                             callback_data=f"a:{pid}:0")])
        if avail["ai"] and not r["examples"]:
            rows.append([Btn(text=t(ui, "btn_ai") + (f" — {r['pinyin']}" if multi else ""),
                             callback_data=f"x:{r['entry_id']}:{lang}")])
    rpid = await ud.put_payload(session, {"q": query, "e": card["readings"][0]["entry_id"]})
    more = webapp_button(settings, t(ui, "more"), card["headword"])
    rows.append([b for b in (
        more, Btn(text=t(ui, "btn_share"), switch_inline_query=card["headword"])) if b])
    rows.append([Btn(text=t(ui, "btn_report"), callback_data=f"r:{rpid}")])
    return rows


@router.callback_query(F.data.startswith("s:"))
async def cb_search_as(cb: CallbackQuery, session: AsyncSession, svc: Services, user: User,
                       settings: Settings):
    data = await ud.get_payload(session, cb.data[2:])
    await cb.answer()
    if not data:
        await cb.message.answer(t(user.ui_lang, "expired"))
        return
    await run_search(cb.message, session, svc, user, settings, data["q"], data["src"])


@router.callback_query(F.data.startswith("e:"))
async def cb_entry(cb: CallbackQuery, session: AsyncSession, svc: Services, user: User,
                   settings: Settings):
    _, eid, *rest = cb.data.split(":")
    entry = await session.get(DictEntry, int(eid))
    await cb.answer()
    if entry:
        await run_search(cb.message, session, svc, user, settings, entry.simplified, "zh",
                         (rest[0] if rest and rest[0] in ("uz", "ru") else None))


# ---------- Озвучка ----------

@router.callback_query(F.data.startswith("a:"))
async def cb_audio(cb: CallbackQuery, session: AsyncSession, svc: Services, user: User,
                   bot: Bot):
    ui = user.ui_lang
    _, pid, slow = cb.data.split(":")
    data = await ud.get_payload(session, pid)
    if not data:
        await cb.answer(t(ui, "expired"), show_alert=True)
        return
    if not (await svc.available(session))["tts"]:
        await cb.answer(t(ui, "tts_unavailable"), show_alert=True)
        return
    if not svc.tts_limiter.allow(user.id):
        await cb.answer(t(ui, "rate_limited"), show_alert=True)
        return
    await cb.answer()
    try:
        audio = await svc.tts.synthesize(data["text"], user.voice or None, slow == "1", "ogg")
    except TTSUnavailable as e:
        await log_event(session, "tts", False, str(e))
        await session.commit()
        await cb.message.answer(t(ui, "tts_failed"))
        return
    await log_event(session, "tts", True, "chat")
    await session.commit()
    await bot.send_voice(cb.message.chat.id, BufferedInputFile(audio, "voice.ogg"),
                         caption=data["text"][:200])


# ---------- Избранное ----------

@router.callback_query(F.data.startswith("f:"))
async def cb_fav(cb: CallbackQuery, session: AsyncSession, user: User):
    ui = user.ui_lang
    data = await ud.get_payload(session, cb.data[2:])
    if not data:
        await cb.answer(t(ui, "expired"), show_alert=True)
        return
    fav = await ud.find_favorite(session, user.id, data["h"], data["p"])
    if fav:
        await ud.remove_favorite(session, user.id, fav.id)
        await cb.answer(t(ui, "unsaved"))
        saved = False
    else:
        await ud.add_favorite(session, user.id, data["h"], data["p"], data["g"], data.get("e"))
        await cb.answer(t(ui, "saved"))
        saved = True
    # Обновляем надпись на нажатой кнопке.
    markup = cb.message.reply_markup
    if markup:
        for row in markup.inline_keyboard:
            for i, b in enumerate(row):
                if b.callback_data == cb.data:
                    w = b.text.split(" ", 2)[2] if b.text.count(" ") >= 2 else ""
                    row[i] = Btn(text=t(ui, "btn_saved" if saved else "btn_save", w=w).strip(),
                                 callback_data=cb.data)
        await cb.message.edit_reply_markup(reply_markup=markup)


@router.message(Command("favorites"))
async def cmd_favorites(message: Message, session: AsyncSession, user: User):
    ui = user.ui_lang
    favs = await ud.list_favorites(session, user.id)
    if not favs:
        await message.answer(t(ui, "fav_empty"))
        return
    lines = [t(ui, "favorites", n=len(favs))]
    rows = []
    for f in favs[:30]:
        lines.append(f"• <b>{escape(f['headword'])}</b> <i>{escape(f['pinyin'])}</i> — "
                     f"{escape(f['gloss'][:60])}")
        rows.append([Btn(text=f"🗑 {f['headword']} {f['pinyin']}", callback_data=f"fd:{f['id']}")])
    rows.insert(0, [Btn(text=t(ui, "review"), callback_data="rv")])
    await message.answer("\n".join(lines), reply_markup=kb(rows[:40]))


@router.callback_query(F.data.startswith("fd:"))
async def cb_fav_delete(cb: CallbackQuery, session: AsyncSession, user: User):
    await ud.remove_favorite(session, user.id, int(cb.data[3:]))
    await cb.answer(t(user.ui_lang, "unsaved"))
    markup = cb.message.reply_markup
    if markup:
        rows = [r for r in markup.inline_keyboard if r[0].callback_data != cb.data]
        await cb.message.edit_reply_markup(reply_markup=kb(rows))


# ---------- Повторение ----------

@router.message(Command("review"))
async def cmd_review(message: Message, session: AsyncSession, user: User):
    await send_review(message, session, user)


@router.callback_query(F.data == "rv")
async def cb_review(cb: CallbackQuery, session: AsyncSession, user: User):
    await cb.answer()
    await send_review(cb.message, session, user)


async def send_review(message: Message, session: AsyncSession, user: User):
    ui = user.ui_lang
    card = await ud.next_review(session, user.id)
    if not card:
        await message.answer(t(ui, "review_empty"))
        return
    await message.answer(t(ui, "review_q", w=escape(card["headword"])),
                         reply_markup=kb([[Btn(text=t(ui, "show_answer"),
                                               callback_data=f"rs:{card['id']}")]]))


@router.callback_query(F.data.startswith("rs:"))
async def cb_review_show(cb: CallbackQuery, session: AsyncSession, user: User):
    ui = user.ui_lang
    fav_id = int(cb.data[3:])
    favs = {f["id"]: f for f in await ud.list_favorites(session, user.id)}
    f = favs.get(fav_id)
    await cb.answer()
    if not f:
        return
    await cb.message.edit_text(
        f"<b>{escape(f['headword'])}</b>\n<i>{escape(f['pinyin'])}</i>\n{escape(f['gloss'])}",
        reply_markup=kb([[Btn(text=t(ui, "knew"), callback_data=f"ra:{fav_id}:1"),
                          Btn(text=t(ui, "didnt"), callback_data=f"ra:{fav_id}:0")]]))


@router.callback_query(F.data.startswith("ra:"))
async def cb_review_answer(cb: CallbackQuery, session: AsyncSession, user: User):
    _, fav_id, knew = cb.data.split(":")
    await ud.answer_review(session, user.id, int(fav_id), knew == "1")
    await cb.answer("✅" if knew == "1" else "🔁")
    await cb.message.edit_reply_markup(reply_markup=None)
    await send_review(cb.message, session, user)


# ---------- AI-пояснение ----------

@router.callback_query(F.data.startswith("x:"))
async def cb_ai(cb: CallbackQuery, session: AsyncSession, svc: Services, user: User):
    ui = user.ui_lang
    _, entry_id, lang = cb.data.split(":")
    if not (await svc.available(session))["ai"]:
        await cb.answer(t(ui, "ai_unavailable"), show_alert=True)
        return
    if not svc.ai_limiter.allow(user.id):
        await cb.answer(t(ui, "rate_limited"), show_alert=True)
        return
    entry = await session.get(DictEntry, int(entry_id))
    await cb.answer("⏳")
    if not entry:
        return
    group = await dic.find_by_headword(session, entry.simplified)
    meanings = [d for e in group if e.pinyin_tone_key == entry.pinyin_tone_key
                for s in e.senses for d in (s.get(lang) or s.get("en") or [])]
    try:
        data = await svc.ai.explain(session, entry.simplified, py.word_marks(entry.pinyin_num),
                                    meanings, lang)
    except AIUnavailable:
        await cb.message.answer(t(ui, "ai_failed"))
        return
    data = {**data, "examples": [{**x, "pinyin": py.text_to_pinyin(x["zh"])}
                                 for x in data.get("examples", [])]}
    await cb.message.answer(f"<b>{escape(entry.simplified)}</b> "
                            f"<i>{escape(py.word_marks(entry.pinyin_num))}</i>\n"
                            + render.ai_text(data, ui))


# ---------- Сообщить об ошибке ----------

@router.callback_query(F.data.startswith("r:"))
async def cb_report(cb: CallbackQuery, session: AsyncSession, user: User, state: FSMContext):
    data = await ud.get_payload(session, cb.data[2:]) or {}
    await state.set_state(ReportState.waiting)
    await state.update_data(q=data.get("q", ""), e=data.get("e"))
    await cb.answer()
    await cb.message.answer(t(user.ui_lang, "report_ask"))


@router.message(ReportState.waiting, F.text, ~F.text.startswith("/"))
async def report_text(message: Message, session: AsyncSession, user: User, state: FSMContext,
                      settings: Settings, bot: Bot):
    data = await state.get_data()
    await state.clear()
    rep = await ud.add_report(session, user.id, data.get("q", ""), message.text, data.get("e"))
    await message.answer(t(user.ui_lang, "report_thanks"))
    for admin_id in settings.admin_ids:  # уведомляем только администраторов
        try:
            await bot.send_message(admin_id, f"⚠️ #{rep.id} «{escape(rep.query)}»\n"
                                             f"{escape(rep.message)}\n/reports")
        except Exception:  # админ мог не запускать бота
            log.warning("cannot notify admin %s", admin_id)


# ---------- История, настройки, удаление данных ----------

@router.message(Command("history"))
async def cmd_history(message: Message, session: AsyncSession, user: User):
    ui = user.ui_lang
    items = await ud.list_history(session, user.id, 15)
    if not items:
        await message.answer(t(ui, "history_empty"))
        return
    rows = []
    for h in items:
        pid = await ud.put_payload(session, {"q": h["query"], "src": None})
        rows.append([Btn(text=h["query"][:50], callback_data=f"s:{pid}")])
    rows.append([Btn(text=t(ui, "clear_history"), callback_data="hc")])
    await session.commit()
    await message.answer(t(ui, "history"), reply_markup=kb(rows))


@router.callback_query(F.data == "hc")
async def cb_history_clear(cb: CallbackQuery, session: AsyncSession, user: User):
    await ud.clear_history(session, user.id)
    await cb.answer()
    await cb.message.edit_text(t(user.ui_lang, "history_cleared"))


def settings_view(user: User):
    ui = user.ui_lang
    other = "ru" if ui == "uz" else "uz"
    other_t = "ru" if user.target_lang == "uz" else "uz"
    return (
        t(ui, "settings", ui=t(ui, f"lang_{ui}"), tgt=t(ui, f"lang_{user.target_lang}")),
        kb([[Btn(text=t(ui, "set_ui", lang=t(ui, f"lang_{other}")), callback_data=f"st:ui:{other}")],
            [Btn(text=t(ui, "set_tgt", lang=t(ui, f"lang_{other_t}")),
                 callback_data=f"st:tgt:{other_t}")],
            [Btn(text=t(ui, "delete_data"), callback_data="del")]]),
    )


@router.message(Command("settings"))
async def cmd_settings(message: Message, user: User):
    text, markup = settings_view(user)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("st:"))
async def cb_settings(cb: CallbackQuery, session: AsyncSession, user: User):
    _, what, val = cb.data.split(":")
    if what == "ui":
        await ud.update_settings(session, user, ui_lang=val)
    else:
        await ud.update_settings(session, user, target_lang=val)
    text, markup = settings_view(user)
    await cb.answer()
    await cb.message.edit_text(text, reply_markup=markup)


@router.message(Command("deletedata"))
async def cmd_delete(message: Message, user: User):
    await ask_delete(message, user)


@router.callback_query(F.data == "del")
async def cb_delete(cb: CallbackQuery, user: User):
    await cb.answer()
    await ask_delete(cb.message, user)


async def ask_delete(message: Message, user: User):
    ui = user.ui_lang
    await message.answer(t(ui, "delete_confirm"), reply_markup=kb([[
        Btn(text=t(ui, "yes_delete"), callback_data="del:yes"),
        Btn(text=t(ui, "no"), callback_data="del:no")]]))


@router.callback_query(F.data.startswith("del:"))
async def cb_delete_confirm(cb: CallbackQuery, session: AsyncSession, user: User):
    ui = user.ui_lang
    await cb.answer()
    if cb.data == "del:yes":
        await ud.delete_all(session, user.id)
        await cb.message.edit_text(t(ui, "deleted"))
    else:
        await cb.message.edit_text(t(ui, "cancelled"))


# ---------- Админ (только ADMIN_IDS) ----------

def is_admin(user: User, settings: Settings) -> bool:
    return user.id in settings.admin_ids


@router.message(Command("admin"))
async def cmd_admin(message: Message, session: AsyncSession, user: User, settings: Settings,
                    svc: Services):
    if not is_admin(user, settings):
        return  # для остальных команды как будто нет
    await message.answer(**await admin_view(session, svc))


async def admin_view(session: AsyncSession, svc: Services) -> dict:
    st = await ud.stats(session)
    flags = await svc.flags(session)
    conf = svc.configured()
    lines = [f"<b>Admin</b> — {st['days']} kun",
             f"Foydalanuvchilar: {st['users_total']} (faol: {st['users_active']})",
             f"Yangi xato xabarlari: {st['reports_new']} — /reports", ""]
    for name, c in sorted(st["services"].items()):
        lines.append(f"{name}: ✅ {c['ok']}  ❌ {c['error']}")
    lines.append("")
    lines.append("Ulangan: " + ", ".join(f"{k} {'✅' if v else '—'}" for k, v in conf.items()))
    for e in st["last_errors"][:5]:
        lines.append(f"• {e['service']}: {escape(e['detail'][:80])}")
    rows = [[Btn(text=f"{'🟢' if flags[k] else '⚪️'} {k}", callback_data=f"ad:flag:{k}")]
            for k in FLAG_DEFAULTS]
    return {"text": "\n".join(lines), "reply_markup": kb(rows)}


@router.callback_query(F.data.startswith("ad:flag:"))
async def cb_admin_flag(cb: CallbackQuery, session: AsyncSession, user: User, settings: Settings,
                        svc: Services):
    if not is_admin(user, settings):
        await cb.answer()
        return
    key = cb.data.split(":")[2]
    if key in FLAG_DEFAULTS:
        flags = await svc.flags(session)
        await session.merge(FeatureFlag(key=key, enabled=not flags[key]))
        await session.commit()
    await cb.answer("OK")
    await cb.message.edit_text(**await admin_view(session, svc))


@router.message(Command("reports"))
async def cmd_reports(message: Message, session: AsyncSession, user: User, settings: Settings):
    if not is_admin(user, settings):
        return
    from sqlalchemy import select
    rows = (await session.scalars(select(ErrorReport).where(ErrorReport.status == "new")
                                  .order_by(ErrorReport.id.desc()).limit(10))).all()
    if not rows:
        await message.answer("Yangi xabarlar yo‘q.")
        return
    for r in rows:
        await message.answer(
            f"#{r.id} · user {r.user_id}\n«{escape(r.query)}»\n{escape(r.message)}",
            reply_markup=kb([[Btn(text="✅ Hal qilindi", callback_data=f"ad:res:{r.id}")]]))


@router.callback_query(F.data.startswith("ad:res:"))
async def cb_admin_resolve(cb: CallbackQuery, session: AsyncSession, user: User,
                           settings: Settings):
    if not is_admin(user, settings):
        await cb.answer()
        return
    rep = await session.get(ErrorReport, int(cb.data.split(":")[2]))
    if rep:
        rep.status = "resolved"
        await session.commit()
    await cb.answer("OK")
    await cb.message.edit_reply_markup(reply_markup=None)


# ---------- Inline-режим (кнопка «Поделиться») ----------

@router.inline_query()
async def inline(query: InlineQuery, session: AsyncSession, svc: Services, user: User):
    q = query.query.strip()
    if not q:
        await query.answer([], cache_time=5, is_personal=True)
        return
    if not svc.search_limiter.allow(user.id):
        await query.answer([], cache_time=5, is_personal=True)
        return
    result = await search(session, svc, q, user_target=user.target_lang)
    if result["type"] == "choose":
        result = await search(session, svc, q, user_target=user.target_lang,
                              source=result["options"][0])
    ui = user.ui_lang
    items = []
    if result["type"] == "word":
        lang = render.meaning_lang(result)
        for i, card in enumerate(result["cards"][:5]):
            r0 = card["readings"][0]
            desc = ", ".join(r0["senses"][0]["items"]) if r0["senses"] else "; ".join(
                (r0.get("english_mt") or r0["english"])[:2])
            items.append(InlineQueryResultArticle(
                id=f"w{i}", title=f"{card['headword']}  {r0['pinyin']}", description=desc[:100],
                input_message_content=InputTextMessageContent(
                    message_text=render.card_text(card, ui, lang))))
    elif result["type"] == "text":
        tx = result["text"]
        items.append(InlineQueryResultArticle(
            id="t0", title=tx.get("translation") or tx["zh"], description=tx["pinyin"][:100],
            input_message_content=InputTextMessageContent(
                message_text=render.text_result(result, ui))))
    elif result["type"] == "candidates":
        for i, c in enumerate(result["candidates"][:10]):
            items.append(InlineQueryResultArticle(
                id=f"c{i}", title=f"{c['headword']}  {c['pinyin']}", description=c["gloss"][:100],
                input_message_content=InputTextMessageContent(
                    message_text=f"<b>{escape(c['headword'])}</b> <i>{escape(c['pinyin'])}</i>"
                                 f" — {escape(c['gloss'])}")))
    await session.commit()
    await query.answer(items, cache_time=30, is_personal=True)


# ---------- Медиа и текст ----------

@router.message(F.voice | F.photo | F.audio | F.video_note)
async def media(message: Message, user: User):
    await message.answer(t(user.ui_lang, "unsupported_media"))


@router.message(F.text & ~F.text.startswith("/"))
async def text_message(message: Message, session: AsyncSession, svc: Services, user: User,
                       settings: Settings):
    await run_search(message, session, svc, user, settings, message.text)
