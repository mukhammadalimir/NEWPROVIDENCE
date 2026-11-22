"""Поиск по словарю и сборка карточек слов.

Источники значений (поле kind в ответе):
  curated   — карточка редакции (uz/ru); verified=False значит «ещё не проверено»;
  cedict_en — CC-CEDICT, английские определения (как есть);
  wikt      — переводы ru/uz из Wiktionary (CC BY-SA 4.0), не проверены редакцией;
  mt        — машинный перевод (Gemini / Google Translate) английских определений или словосочетаний;
  bkrs      — 大БКРС (bkrs.info), человеческие русские значения; для uz — bkrs_mt (их перевод ru→uz).
"""

import re
from collections import OrderedDict

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BkrsEntry, DictEntry, DictGloss, WiktPair
from app.services import bkrs
from app.services.container import Services
from app.services.translate import TranslationUnavailable
from app.text import dsl
from app.text import pinyin as py
from app.text import uzbek

MAX_COLLOCATIONS = 6


async def find_by_headword(session: AsyncSession, text: str) -> list[DictEntry]:
    rows = await session.scalars(
        select(DictEntry)
        .where(or_(DictEntry.simplified == text, DictEntry.traditional == text))
        .order_by(DictEntry.id))
    return list(rows.all())


async def find_by_pinyin(session: AsyncSession, syls: list[py.Syllable],
                         limit: int = 300) -> list[DictEntry]:
    toneless = py.toneless_key(syls)
    stmt = select(DictEntry).where(DictEntry.pinyin_key == toneless)
    if all(s.tone for s in syls):
        stmt = select(DictEntry).where(DictEntry.pinyin_tone_key == py.tone_key(syls))
    rows = list((await session.scalars(stmt.order_by(DictEntry.freq.desc()).limit(limit))).all())
    if py.has_tones(syls) and not all(s.tone for s in syls):
        # Тоны указаны только у части слогов — фильтруем по ним.
        rows = [e for e in rows if _tones_match(e.pinyin_tone_key, syls)]
    return rows


def _tones_match(tone_key: str, syls: list[py.Syllable]) -> bool:
    parsed = py.parse(tone_key)
    if not parsed or len(parsed) != len(syls):
        return False
    return all(q.tone is None or q.tone == (p.tone or 5) for q, p in zip(syls, parsed))


def gloss_term(lang: str, text: str) -> str:
    if lang == "uz":
        return uzbek.normalize(text)
    return text.lower().replace("ё", "е").strip(" .,!?")


async def find_by_gloss(session: AsyncSession, lang: str, text: str) -> list[DictEntry]:
    """Карточки редакции; если ровно одно такое слово — только оно.
    Иначе добавляются переводы Wiktionary (в порядке их надёжности)."""
    term = gloss_term(lang, text)
    rows = await session.scalars(
        select(DictEntry).join(DictGloss, DictGloss.entry_id == DictEntry.id)
        .where(DictGloss.lang == lang, DictGloss.term == term)
        .order_by(DictEntry.freq.desc(), DictEntry.id))
    found = list(OrderedDict((e.id, e) for e in rows.all()).values())
    have = {e.simplified for e in found}
    if len(have) == 1:
        return found
    zhs = [z for z in (await session.scalars(
        select(WiktPair.zh).where(WiktPair.lang == lang, WiktPair.term == term)
        .order_by(WiktPair.rank))).all() if z not in have]
    if zhs:
        extra = (await session.scalars(
            select(DictEntry).where(DictEntry.simplified.in_(zhs), DictEntry.source == "cedict")
            .order_by(DictEntry.id))).all()
        extra = [e for e in extra if not e.pinyin_num[:1].isupper()]
        found += sorted(extra, key=lambda e: zhs.index(e.simplified))
    return found


async def wikt_meanings(session: AsyncSession, lang: str, heads) -> dict[str, list[str]]:
    """Русские/узбекские значения китайских слов по Wiktionary (самые прямые — первыми)."""
    heads = list(set(heads))
    if lang not in ("ru", "uz") or not heads:
        return {}
    rows = (await session.execute(
        select(WiktPair.zh, WiktPair.term, WiktPair.rank)
        .where(WiktPair.lang == lang, WiktPair.zh.in_(heads)))).all()
    out: dict[str, list[tuple[int, int, str]]] = {}
    for zh, term, rank in rows:
        out.setdefault(zh, []).append((rank, len(term), term))
    return {zh: [t for _, _, t in sorted(v)][:5] for zh, v in out.items()}


def group_by_headword(entries: list[DictEntry]) -> "OrderedDict[str, list[DictEntry]]":
    groups: OrderedDict[str, list[DictEntry]] = OrderedDict()
    for e in entries:
        groups.setdefault(e.simplified, []).append(e)
    return groups


_WEAK_DEF = re.compile(r"^(old |archaic )?(variant of|surname|used in|see )", re.I)


def short_gloss(entries: list[DictEntry], lang: str,
                wikt: dict[str, list[str]] | None = None) -> tuple[str, str]:
    """Короткое значение для списков: (текст, источник)."""
    for e in entries:
        if e.source == "curated":
            for s in e.senses:
                if s.get(lang):
                    return ", ".join(s[lang][:3]), "curated"
    if wikt and entries and wikt.get(entries[0].simplified):
        return ", ".join(wikt[entries[0].simplified][:3]), "wikt"
    # Обычные слова раньше имён собственных; «variant of…» — в последнюю очередь.
    ordered = sorted(entries, key=lambda e: e.pinyin_num[:1].isupper())
    defs = [d for e in ordered for s in e.senses for d in s.get("en", [])]
    good = [d for d in defs if not _WEAK_DEF.match(d)] or defs
    return ("; ".join(good[:2]), "cedict_en") if good else ("", "")


async def complete_with_cedict(session: AsyncSession, entries: list[DictEntry]) -> list[DictEntry]:
    """Добавляет к редакционным карточкам статьи CC-CEDICT того же написания и чтения."""
    keys = {(e.simplified, *_reading_key(e)) for e in entries}
    if not keys:
        return entries
    extra = await session.scalars(select(DictEntry).where(
        DictEntry.source == "cedict",
        DictEntry.simplified.in_({k[0] for k in keys})).order_by(DictEntry.id))
    return entries + [e for e in extra.all() if (e.simplified, *_reading_key(e)) in keys]


def _reading_key(e: DictEntry) -> tuple[str, bool]:
    return e.pinyin_tone_key, e.pinyin_num[:1].isupper()


async def _collocation_pool(session: AsyncSession, headword: str) -> list[DictEntry]:
    n = len(headword)
    rows = await session.scalars(
        select(DictEntry)
        .where(DictEntry.source == "cedict",
               DictEntry.simplified.contains(headword),
               DictEntry.simplified != headword,
               func.length(DictEntry.simplified).between(n + 1, n + 3),
               DictEntry.freq > 0)
        .order_by(DictEntry.freq.desc())
        .limit(80))
    return list(rows.all())


def _matches_reading(compound: DictEntry, headword: str, reading_tone_key: str,
                     all_keys: list[str] | None = None, allow_neutral: bool = True) -> bool:
    """Чтение иероглифа внутри составного слова совпадает с нужным чтением?

    Пример: 银行 yin2 hang2 относится к 行 háng, а не к 行 xíng.
    Нейтральный тон (狗东西 gou3 dong1 xi5) подходит к любому чтению с теми же слогами,
    но только если у слова нет чтения, совпадающего точно (东西 dōngxi, а не dōngxī).
    """
    parts = compound.pinyin_num.lower().replace("u:", "v").split()
    if len(parts) != len(compound.simplified):
        return False
    i = compound.simplified.find(headword)
    sub = "".join(parts[i:i + len(headword)])
    want = reading_tone_key
    strip5 = lambda s: s.replace("5", "")  # noqa: E731  нейтральный тон в составе слова
    exact = lambda k: sub == k or strip5(sub) == strip5(k)  # noqa: E731
    if exact(want):
        return True
    if not allow_neutral or (all_keys and any(exact(k) for k in all_keys)):
        return False
    return py.keys_from_numbered(sub)[1] == py.keys_from_numbered(want)[1] and "5" in sub


async def build_cards(session: AsyncSession, svc: Services, entries: list[DictEntry],
                      lang: str, avail: dict[str, bool]) -> tuple[list[dict], list[str]]:
    """Карточки: одна на написание, внутри — отдельные чтения со своими значениями.

    Возвращает (карточки, уведомления), например ["translate_failed"].
    """
    cards = []
    to_translate: list[str] = []  # английские определения и словосочетания для MT
    wikt = await wikt_meanings(session, lang, (e.simplified for e in entries))

    for headword, group in group_by_headword(entries).items():
        trad = next((e.traditional for e in group if e.traditional != headword), None)
        readings: OrderedDict[tuple, list[DictEntry]] = OrderedDict()
        # Сначала редакционные карточки, затем обычные слова, затем имена собственные.
        for e in sorted(group, key=lambda e: (e.source != "curated", _reading_key(e)[1], e.id)):
            readings.setdefault(_reading_key(e), []).append(e)

        pool = await _collocation_pool(session, headword) if avail.get("collocations") else []
        common = [k for k in readings if not k[1]]
        all_keys = [k[0] for k in readings]
        card_readings = []
        for (tone_key, proper), items in readings.items():
            curated = [e for e in items if e.source == "curated"]
            cedict = [e for e in items if e.source == "cedict"]
            main = curated[0] if curated else items[0]
            senses = [
                {"pos": _pos(s.get("pos"), lang), "items": s.get(lang) or [], "kind": "curated",
                 "verified": e.verified}
                for e in curated for s in e.senses if s.get(lang)
            ]
            # Wiktionary не различает чтения — его значения только при одном обычном чтении.
            if not senses and wikt.get(headword) and common == [(tone_key, proper)]:
                senses.append({"pos": None, "items": wikt[headword], "kind": "wikt",
                               "verified": False})
            english = [d for e in cedict for s in e.senses for d in s.get("en", [])]
            english += [d for e in curated for s in e.senses for d in s.get("en", [])]
            measure = next((e.measure_word for e in curated + cedict if e.measure_word), None)
            usage = next(({"text": e.usage[lang], "kind": "curated"}
                          for e in curated if e.usage.get(lang)), None)
            examples = [
                {"zh": x["zh"], "pinyin": x.get("pinyin") or py.text_to_pinyin(x["zh"]),
                 "translation": x.get(lang), "kind": "curated"}
                for e in curated for x in e.examples
            ]
            collocations = [
                {"zh": c["zh"], "pinyin": c.get("pinyin", ""), "gloss": c.get(lang, ""),
                 "gloss_kind": "curated"}
                for e in curated for c in e.collocations
            ]
            seen = {c["zh"] for c in collocations}
            for c in pool:
                if len(collocations) >= MAX_COLLOCATIONS:
                    break
                if c.simplified in seen or not _matches_reading(c, headword, tone_key, all_keys):
                    continue
                seen.add(c.simplified)
                en = next((s["en"] for s in c.senses if s.get("en")), [])
                collocations.append({
                    "zh": c.simplified, "pinyin": py.word_marks(c.pinyin_num),
                    "gloss": "; ".join(en[:2]), "gloss_kind": "cedict_en", "_mt": True,
                    # подошло только «по слогам» (нейтральный тон): решим ниже, к какому чтению
                    "_neutral": not _matches_reading(c, headword, tone_key, all_keys,
                                                     allow_neutral=False)})
            reading = {
                "entry_id": main.id,
                "key": tone_key,
                "pinyin": py.word_marks(main.pinyin_num),
                "pinyin_num": main.pinyin_num,
                "approx": py.approx_uz(main.pinyin_num),
                "proper": proper,
                "measure_word": measure,
                "senses": senses,
                "english": english,
                "english_mt": None,
                "usage": usage,
                "examples": examples,
                "collocations": collocations,
                "has_curated": bool(curated),
            }
            card_readings.append(reading)
        cards.append({"headword": headword, "traditional": trad, "readings": card_readings})

    # 大БКРС: человеческие значения на русском (для uz — их перевод) вместо английских.
    notices = await attach_bkrs(session, svc, cards, lang)
    _neutral_collocations_to_main_reading(cards)
    collocs = [c for card in cards for r in card["readings"] for c in r["collocations"]
               if c.get("_mt")]
    await bkrs.apply_short_glosses(session, svc, collocs, lang)
    for card in cards:
        for r in card["readings"]:
            for c in r["collocations"]:
                if c.get("gloss_kind", "").startswith("bkrs"):
                    c.pop("_mt", None)
            if avail.get("translate") and lang != "en":
                if not r.get("bkrs"):
                    to_translate.extend(r["english"])
                to_translate.extend(c["zh"] for c in r["collocations"] if c.get("_mt"))

    # Машинный перевод одним запросом на всю выдачу (результат помечается как "mt").
    translated: dict[str, str] = {}
    if to_translate and svc.translator:
        uniq = list(OrderedDict.fromkeys(to_translate))
        en_items = [t for t in uniq if not _has_han(t)]
        zh_items = [t for t in uniq if _has_han(t)]
        try:
            if en_items:
                translated.update(zip(en_items, await svc.translator.translate(
                    session, en_items, "en", lang)))
            if zh_items:
                translated.update(zip(zh_items, await svc.translator.translate(
                    session, zh_items, "zh", lang)))
        except TranslationUnavailable:
            if "translate_failed" not in notices:
                notices.append("translate_failed")
    for card in cards:
        for r in card["readings"]:
            if r["english"] and all(d in translated for d in r["english"]):
                r["english_mt"] = [translated[d] for d in r["english"]]
            for c in r["collocations"]:
                if c.pop("_mt", False) and c["zh"] in translated:
                    c["gloss"] = translated[c["zh"]]
                    c["gloss_kind"] = "mt"
    return cards, notices


async def attach_bkrs(session: AsyncSession, svc: Services, cards: list[dict],
                      lang: str) -> list[str]:
    """Добавляет к чтениям карточек значения БКРС (reading["bkrs"], reading["bkrs_kind"])."""
    found = await bkrs.find(session, (c["headword"] for c in cards))
    groups = []
    for card in cards:
        e = found.get(card["headword"])
        if not e:
            continue
        readings, items = bkrs.parsed(e)
        by = dsl.assign_readings(items, readings,
                                 [r["pinyin"] for r in card["readings"]])
        for r in card["readings"]:
            sel = bkrs.select_items(by.get(r["pinyin"], []))
            if sel:
                r["bkrs"] = sel
                groups.append(sel)
        # Порядок чтений — как в БКРС (打: сначала dǎ «бить», потом dá «дюжина»);
        # имена собственные по-прежнему в конце.
        order = [dsl.norm_pinyin(x) for x in bkrs.entry_readings(e, items)]
        rank = lambda r: (r["proper"], order.index(dsl.norm_pinyin(r["pinyin"]))  # noqa: E731
                          if dsl.norm_pinyin(r["pinyin"]) in order else len(order))
        card["readings"].sort(key=rank)
    if not groups:
        return []
    kind = await bkrs.translate_items(session, svc, groups, lang)
    for card in cards:
        for r in card["readings"]:
            if r.get("bkrs"):
                r["bkrs_kind"] = kind
    return []  # «перевод недоступен» показывается в самой карточке (bkrs_kind = bkrs_ru)


async def build_bkrs_cards(session: AsyncSession, svc: Services, entry: BkrsEntry,
                           lang: str) -> tuple[list[dict], list[str]]:
    """Карточка для слова/выражения, которое есть только в БКРС (нет в CC-CEDICT)."""
    _, items = bkrs.parsed(entry)
    readings = bkrs.entry_readings(entry, items) or [py.text_to_pinyin(entry.headword)]
    card_readings = []
    for rd in readings:
        num = bkrs.marks_to_numbered(rd)
        card_readings.append({
            "entry_id": None, "key": num.replace(" ", ""), "pinyin": rd, "pinyin_num": num,
            "approx": py.approx_uz(num) if num else "", "proper": rd[:1].isupper(),
            "measure_word": None, "senses": [], "english": [], "english_mt": None,
            "usage": None, "examples": [], "collocations": [], "has_curated": False,
        })
    card = {"headword": entry.headword, "traditional": None, "readings": card_readings}
    notices = await attach_bkrs(session, svc, [card], lang)
    card["readings"] = [r for r in card["readings"] if r.get("bkrs")] or card["readings"][:1]
    return [card], notices


def _neutral_collocations_to_main_reading(cards: list[dict]) -> None:
    """Словосочетание с нейтральным тоном (拍打 pāida) подходит к любому чтению по слогам;
    оставляем его только у основного (первого обычного) чтения — после сортировки по БКРС."""
    for card in cards:
        common = [r for r in card["readings"] if not r["proper"]] or card["readings"]
        main = common[0] if common else None
        for r in card["readings"]:
            r["collocations"] = [c for c in r["collocations"]
                                 if not c.get("_neutral") or r is main]
            for c in r["collocations"]:
                c.pop("_neutral", None)


def reading_gloss(r: dict) -> str:
    """Короткое значение чтения для избранного, inline-режима и т.п."""
    if r.get("bkrs"):
        g = bkrs.short(r["bkrs"])
        if g:
            return g
    if r.get("senses"):
        return ", ".join(r["senses"][0]["items"])
    return "; ".join((r.get("english_mt") or r.get("english") or [])[:2])


def _pos(pos, lang: str) -> str | None:
    return pos.get(lang) if isinstance(pos, dict) else pos


def _has_han(s: str) -> bool:
    return any("㐀" <= ch <= "鿿" for ch in s)
