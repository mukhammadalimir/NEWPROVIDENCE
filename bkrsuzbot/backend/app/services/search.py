"""Единая точка поиска для бота и Mini App.

Тип результата (поле "type"):
  word        — карточки слова;
  candidates  — несколько подходящих слов (например, по пиньиню "yu");
  text        — перевод фразы/текста;
  choose      — ввод неоднозначен, нужно выбрать язык (не угадываем молча);
  not_found   — ничего не найдено.
Поле "notices" — служебные пометки: mt_used, translate_unavailable, translate_failed.
"""

import re

import jieba
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DictEntry
from app.services import dictionary as dic
from app.services.container import Services
from app.services.events import log_event
from app.services.translate import TranslationUnavailable
from app.text import detect as det
from app.text import pinyin as py
from app.text import uzbek

MAX_QUERY = 500
MAX_CANDIDATES = 20
WORD_MAX_HAN = 6  # до скольки иероглифов пробуем искать как слово
WORD_MAX_WORDS = 3  # до скольки узбекских/русских слов пробуем словарь


def target_for(source: str, user_target: str, forced_target: str | None) -> str:
    if source in (det.ZH, det.PINYIN):
        return forced_target if forced_target in ("uz", "ru") else user_target
    return "zh"


async def search(session: AsyncSession, svc: Services, query: str, *, user_target: str = "uz",
                 source: str | None = None, target: str | None = None) -> dict:
    query = re.sub(r"\s+", " ", query.strip())[:MAX_QUERY]
    avail = await svc.available(session)
    base = {"query": query, "notices": [], "alternatives": []}
    if not query:
        return {**base, "type": "not_found"}

    if source not in det.SOURCES:
        d = det.detect(query)
        if d.lang is None and set(d.options) >= {"ru", "uz"} and len(query.split()) <= WORD_MAX_WORDS:
            # Кириллица без узбекских букв: если слово есть только в одном словаре — берём его.
            hits = [lg for lg in ("ru", "uz") if await dic.find_by_gloss(session, lg, query)]
            if len(hits) == 1:
                other = "uz" if hits[0] == "ru" else "ru"
                d = det.Detection(hits[0], [], [other])
        if d.lang is None:
            await log_event(session, "search", True, "choose")
            await session.commit()
            return {**base, "type": "choose", "options": d.options}
        source, base["alternatives"] = d.lang, d.alternatives

    lang = target_for(source, user_target, target)
    base.update(source_lang=source, target_lang=lang)

    if source == det.ZH:
        result = await _search_zh(session, svc, query, lang, avail, base)
    elif source == det.PINYIN:
        result = await _search_pinyin(session, svc, query, lang, avail, base)
    else:
        result = await _search_word_lang(session, svc, query, source, user_target, avail, base)

    await log_event(session, "search", result["type"] != "not_found",
                    f"{source}:{result['type']}")
    await session.commit()
    return result


async def _search_zh(session, svc, query, lang, avail, base) -> dict:
    han_only = re.sub(r"[\s，。！？、,.!?]", "", query)
    if len(han_only) <= WORD_MAX_HAN:
        entries = await dic.find_by_headword(session, han_only)
        if entries:
            cards, notices = await dic.build_cards(session, svc, entries, lang, avail)
            return {**base, "type": "word", "cards": cards, "notices": notices}
    return await _text_from_zh(session, svc, query, lang, avail, base)


async def _search_pinyin(session, svc, query, lang, avail, base) -> dict:
    syls = py.parse(query)
    if not syls:
        return {**base, "type": "not_found"}
    entries = await dic.find_by_pinyin(session, syls)
    groups = dic.group_by_headword(entries)
    if not groups:
        return {**base, "type": "not_found"}
    if len(groups) == 1:
        cards, notices = await dic.build_cards(session, svc, entries, lang, avail)
        return {**base, "type": "word", "cards": cards, "notices": notices}
    wikt = await dic.wikt_meanings(session, lang, list(groups)[:MAX_CANDIDATES * 3])
    return {**base, "type": "candidates",
            "candidates": _candidates(groups, lang, syls, wikt)[:MAX_CANDIDATES]}


def _candidates(groups, lang, syls=None, wikt=None, order=None) -> list[dict]:
    out = []
    for headword, items in groups.items():
        # Для поиска по пиньиню показываем только подходящие чтения.
        if syls:
            want = py.toneless_key(syls)
            items = [e for e in items if e.pinyin_key == want] or items
        gloss, kind = dic.short_gloss(items, lang, wikt)
        pinyins = list(dict.fromkeys(py.word_marks(e.pinyin_num) for e in items
                                     if not e.pinyin_num[:1].isupper()))
        pinyins = pinyins or list(dict.fromkeys(py.word_marks(e.pinyin_num) for e in items))
        out.append({"headword": headword, "pinyin": ", ".join(pinyins[:3]),
                    "gloss": gloss, "gloss_kind": kind, "entry_id": items[0].id,
                    "_rank": (order.get(headword, 99) if order else int(kind != "curated"),
                              -max(e.freq for e in items))})
    out.sort(key=lambda c: c.pop("_rank"))
    return out


async def _search_word_lang(session, svc, query, source, user_target, avail, base) -> dict:
    """Узбекский или русский ввод → китайский."""
    words = query.split()
    if len(words) <= WORD_MAX_WORDS:
        entries = await dic.find_by_gloss(session, source, query)
        groups = dic.group_by_headword(entries)
        if len(groups) == 1:
            entries = await dic.complete_with_cedict(session, entries)
            cards, notices = await dic.build_cards(session, svc, entries, source, avail)
            return {**base, "type": "word", "cards": cards, "notices": notices}
        if len(groups) > 1:
            wikt = await dic.wikt_meanings(session, source, list(groups))
            order = {h: (0 if any(e.source == "curated" for e in g) else 1 + i)
                     for i, (h, g) in enumerate(groups.items())}
            return {**base, "type": "candidates",
                    "candidates": _candidates(groups, source, wikt=wikt, order=order)[:MAX_CANDIDATES]}

    if not avail["translate"]:
        return {**base, "type": "not_found", "notices": ["translate_unavailable"]}

    src_text = uzbek.cyr_to_lat(query) if source == "uz" else query
    try:
        (zh,) = await svc.translator.translate(session, [src_text], source, "zh")
    except TranslationUnavailable:
        return {**base, "type": "not_found", "notices": ["translate_failed"]}
    zh = zh.strip()
    if len(words) <= WORD_MAX_WORDS and 0 < len(zh) <= 4:
        entries = await dic.find_by_headword(session, zh.strip("。！？"))
        if entries:
            cards, notices = await dic.build_cards(session, svc, entries, source, avail)
            return {**base, "type": "word", "cards": cards, "mt_headword": zh,
                    "notices": ["mt_used", *notices]}
    seg = _segment(zh)
    return {**base, "type": "text", "notices": ["mt_used"], "text": {
        "source": query, "translation": zh, "zh": zh,
        "pinyin": py.text_to_pinyin(zh, seg),
        "words": await _word_breakdown(session, seg, source),
        "provider": svc.translator.label}}


async def _text_from_zh(session, svc, query, lang, avail, base) -> dict:
    seg = _segment(query)
    text = {"source": query, "translation": None, "zh": query,
            "pinyin": py.text_to_pinyin(query, seg),
            "words": await _word_breakdown(session, seg, lang), "provider": None}
    notices = []
    if avail["translate"]:
        try:
            (text["translation"],) = await svc.translator.translate(session, [query], "zh", lang)
            text["provider"] = svc.translator.label
            notices.append("mt_used")
        except TranslationUnavailable:
            notices.append("translate_failed")
    else:
        notices.append("translate_unavailable")
    return {**base, "type": "text", "text": text, "notices": notices}


def _segment(zh: str) -> list[str]:
    return [w for w in jieba.lcut(zh) if w.strip()]


async def _word_breakdown(session, words: list[str], lang: str) -> list[dict]:
    """Разбор китайского текста по словам (со словарными значениями)."""
    out, seen = [], set()
    wikt = await dic.wikt_meanings(session, lang, [w for w in words if dic._has_han(w)])
    for w in words:
        if w in seen or not dic._has_han(w):
            continue
        seen.add(w)
        entries: list[DictEntry] = await dic.find_by_headword(session, w)
        if not entries:
            continue
        gloss, kind = dic.short_gloss(entries, lang, wikt)
        out.append({"zh": w, "pinyin": py.word_marks(entries[0].pinyin_num),
                    "gloss": gloss, "gloss_kind": kind})
        if len(out) >= 15:
            break
    return out
