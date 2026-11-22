"""Значения из 大БКРС (bkrs.info) — человеческого китайско-русского словаря.

- Русский: значения показываются как в БКРС (тот же порядок, пометы, примеры).
- Узбекский: те же строки БКРС переводятся ru→uz (Gemini / Google), перевод кэшируется;
  если перевод недоступен — показывается русский оригинал с пометкой.

Источник в выдаче: kind "bkrs" (оригинал) или "bkrs_mt" (машинный перевод БКРС).
"""

import re
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BkrsEntry
from app.services.container import Services
from app.services.translate import TranslationUnavailable
from app.text import dsl
from app.text import pinyin as py

MAX_ITEMS = 40  # строк статьи на одно чтение
MAX_EX_PER_SENSE = 2  # примеров к одному значению
MAX_CHARS = 1800  # символов БКРС на одно чтение (лимит сообщения Telegram — 4096)
MAX_LOOKUP_LEN = 40
_NUM_RE = re.compile(r"^\s*(?:[IVXL]+\s+)?(?:\d+\)|[а-яa-z]\))\s*")


REF_ONLY_RE = re.compile(r"\[m1\](?:\[p\])?см\.(?:\[/p\])?\s*\[ref\]([^\[]+)\[/ref\]\s*\[/m\]")


async def _fetch(session: AsyncSession, heads: list[str]) -> dict[str, BkrsEntry]:
    out: dict[str, BkrsEntry] = {}
    for i in range(0, len(heads), 500):
        rows = await session.scalars(select(BkrsEntry).where(
            BkrsEntry.headword.in_(heads[i:i + 500])).order_by(BkrsEntry.id))
        for e in rows.all():
            out.setdefault(e.headword, e)
    return out


async def find(session: AsyncSession, headwords: Iterable[str]) -> dict[str, BkrsEntry]:
    """Статьи БКРС по точному написанию (первая статья для каждого написания).
    Статья-ссылка «см. X» заменяется статьёй X (как переход по ссылке на сайте)."""
    heads = list(dict.fromkeys(h for h in headwords if h and len(h) <= MAX_LOOKUP_LEN))
    out = await _fetch(session, heads)
    refs = {h: m.group(1).strip() for h, e in out.items()
            if (m := REF_ONLY_RE.fullmatch(e.body.strip()))}
    if refs:
        targets = await _fetch(session, list(set(refs.values())))
        for h, target in refs.items():
            if target in targets:
                out[h] = targets[target]
    return out


def select_items(items: list[dict]) -> list[dict]:
    """Что показать в карточке: значения по порядку БКРС, к каждому — до 2 примеров."""
    out, chars, ex_run = [], 0, 0
    for it in items:
        if it["kind"] == "ex":
            ex_run += 1
            if ex_run > MAX_EX_PER_SENSE:
                continue
        else:
            ex_run = 0
        size = len(it["text"])
        if out and (len(out) >= MAX_ITEMS or chars + size > MAX_CHARS):
            break
        out.append(dict(it))
        chars += size
    # заголовок раздела без значений после него не нужен
    while out and out[-1]["kind"] == "head":
        out.pop()
    return out


def short(items: list[dict], key: str = "text") -> str:
    """Короткое значение для списков: первое значение без нумерации."""
    for it in items:
        if it["kind"] == "sense":
            s = _NUM_RE.sub("", it.get(key) or it["text"]).strip()
            return s if len(s) <= 80 else s[:80].rsplit(" ", 1)[0] + "…"
    return ""


def marks_to_numbered(reading: str) -> str:
    """«dǎ» → «da3», «mǎmǎhūhū» → «ma3 ma3 hu1 hu1» (для приблизительного звучания)."""
    syls = py.parse(re.sub(r"[,，;]", " ", reading))
    if not syls:
        return ""
    return " ".join(f"{s.text.replace('v', 'u:')}{s.tone or 5}" for s in syls)


def parsed(entry: BkrsEntry) -> tuple[list[str], list[dict]]:
    """(чтения из строки пиньиня, строки статьи) — единая точка разбора статьи."""
    readings = dsl.readings_of(entry.pinyin, entry.headword)
    return readings, dsl.parse_body(entry.body, readings)


def entry_readings(entry: BkrsEntry, items: list[dict]) -> list[str]:
    """Чтения статьи по порядку: сначала строка пиньиня (её порядок — как на сайте:
    那 nà раньше nǎ), затем размеченные в тексте чтения, которых там нет ([b]dōngxi[/b]
    при строке «dōngxī, dongxi»). Чтение без тонов, повторяющее найденное, пропускаем."""
    seen, out = set(), []
    for r in dsl.readings_of(entry.pinyin, entry.headword) + [
            it["reading"] for it in items if it["reading"]]:
        k = dsl.norm_pinyin(r)
        if not dsl.is_reading(re.sub(r"[,，;]", " ", r)) or k in seen:
            continue
        if k == dsl.strip_tones(r) and any(dsl.strip_tones(x) == k for x in out):
            continue
        seen.add(k)
        out.append(r)
    return out


def short_for(entry: BkrsEntry, pinyin: str | None = None) -> str:
    """Короткое значение статьи; если задано чтение и в статье их несколько — значение
    именно этого чтения ("" — если такого чтения в статье нет)."""
    readings, items = parsed(entry)
    own = entry_readings(entry, items)
    if not pinyin or len(own) <= 1:
        return short(items)
    by = dsl.assign_readings(items, readings, own)  # строки по чтениям самой статьи
    key = dsl.match_reading(pinyin.split(",")[0].strip(), list(by))
    return short(by[key]) if key else ""


async def translate_items(session: AsyncSession, svc: Services, groups: list[list[dict]],
                          lang: str) -> str:
    """Готовит строки к показу на языке lang. Возвращает вид источника:
    "bkrs" (русский оригинал), "bkrs_mt" (переведено), "bkrs_ru" (перевод недоступен)."""
    if lang != "uz":
        return "bkrs"
    texts: list[str] = []
    for items in groups:
        for it in items:
            if it["kind"] == "ex":
                if it["tr"]:
                    texts.append(it["tr"])
            else:
                texts.append(it["text"])
    if not texts:
        return "bkrs"
    if not svc.translator or not (await svc.available(session))["translate"]:
        return "bkrs_ru"
    uniq = list(dict.fromkeys(texts))
    try:
        done = dict(zip(uniq, await svc.translator.translate(session, uniq, "ru", "uz")))
    except TranslationUnavailable:
        return "bkrs_ru"
    for items in groups:
        for it in items:
            if it["kind"] == "ex":
                it["tr"] = done.get(it["tr"], it["tr"])
                it["text"] = f"{it['zh']} {it['tr']}".strip()
            else:
                it["text"] = done.get(it["text"], it["text"])
    return "bkrs_mt"


async def apply_short_glosses(session: AsyncSession, svc: Services, rows: list[dict],
                              lang: str, key: str = "zh") -> None:
    """Короткие значения БКРС для списков (разбор фразы по словам, кандидаты, словосочетания).
    Меняет rows на месте: gloss / gloss_kind = bkrs | bkrs_mt.

    ru — значение БКРС всегда (как на сайте).
    uz — значение редакции (человеческий узбекский) не трогаем; остальное — перевод БКРС;
         если перевода нет — русский БКРС вместо английского CC-CEDICT (узбекский
         Wiktionary оставляем: он хотя бы на узбекском)."""
    if lang not in ("ru", "uz") or not rows:
        return
    if lang == "uz":
        rows = [r for r in rows if r.get("gloss_kind") != "curated"]
    entries = await find(session, (r[key] for r in rows))
    # значение того чтения, что показано в строке (кандидат «yú», словосочетание и т.п.)
    glosses: dict[int, str] = {}
    for i, r in enumerate(rows):
        e = entries.get(r[key])
        g = short_for(e, r.get("pinyin")) if e else ""
        if g:
            glosses[i] = g
    if not glosses:
        return
    if lang == "uz":
        done: dict[str, str] = {}
        if svc.translator and (await svc.available(session))["translate"]:
            uniq = list(dict.fromkeys(glosses.values()))
            try:
                done = dict(zip(uniq, await svc.translator.translate(session, uniq, "ru", "uz")))
            except TranslationUnavailable:
                done = {}
        for i, r in enumerate(rows):
            g = glosses.get(i)
            if not g:
                continue
            if g in done:
                r["gloss"], r["gloss_kind"] = done[g], "bkrs_mt"
            elif r.get("gloss_kind") in ("cedict_en", "", "_bkrs_only"):
                r["gloss"], r["gloss_kind"] = g, "bkrs"
        return
    for i, r in enumerate(rows):
        if i in glosses:
            r["gloss"], r["gloss_kind"] = glosses[i], "bkrs"
