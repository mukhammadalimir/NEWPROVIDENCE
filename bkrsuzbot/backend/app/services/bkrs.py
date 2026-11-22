"""Значения из 大БКРС (bkrs.info) — человеческого китайско-русского словаря.

- Русский: значения показываются как в БКРС (тот же порядок, пометы, примеры).
- Узбекский: те же строки БКРС переводятся ru→uz (Gemini / Google), перевод кэшируется
  и проверяется (translate.uz_problem); строки без перевода показываются по-русски.

Вид источника строк карточки (reading["bkrs_kind"]):
  bkrs      — русский оригинал (выбран русский);
  bkrs_mt   — всё переведено на узбекский;
  bkrs_part — часть строк переведена, остальные по-русски;
  bkrs_ru   — перевода нет, показан русский.
В списках (gloss_kind): bkrs (ru), bkrs_mt (uz), bkrs_ru (русский в узбекском режиме).
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

MAX_ITEMS = 40  # строк статьи на одно чтение (бот)
MAX_EX_PER_SENSE = 2  # примеров к одному значению
MAX_CHARS = 1800  # символов БКРС на одно чтение в боте (лимит сообщения Telegram — 4096)
# автономная Mini App: ограничения Telegram нет — показываем почти всю статью
OFFLINE_MAX_ITEMS = 160
OFFLINE_MAX_CHARS = 7000
MAX_LOOKUP_LEN = 40
_NUM_RE = re.compile(r"^\s*(?:[IVXL]+\s+)?(?:\d+\)|[а-яa-z]\))\s*")
_REF_RE = re.compile(r"^(?:см\.|вм\.|qarang|o‘rniga)\s", re.I)
CYR_RE = re.compile(r"[А-Яа-яЁё]")


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


def has_russian(items: list[dict]) -> bool:
    """В БКРС есть статьи без русского (английский или китайский текст) — они не лучше
    английского CC-CEDICT, поэтому такие статьи не показываем вместо него."""
    return any(CYR_RE.search(it["tr"] if it["kind"] == "ex" else it["text"]) for it in items)


def select_items(items: list[dict], max_items: int = MAX_ITEMS,
                 max_chars: int = MAX_CHARS) -> list[dict]:
    """Что показать: значения по порядку БКРС, к каждому — до 2 примеров."""
    out, chars, ex_run = [], 0, 0
    for it in items:
        if it["kind"] == "ex":
            ex_run += 1
            if ex_run > MAX_EX_PER_SENSE:
                continue
        else:
            ex_run = 0
        size = len(it["text"])
        if out and (len(out) >= max_items or chars + size > max_chars):
            break
        out.append(dict(it))
        chars += size
    # заголовок раздела без значений после него не нужен
    while out and out[-1]["kind"] == "head":
        out.pop()
    return out


def first_sense(items: list[dict], key: str = "text") -> str:
    """Полный текст значения для коротких подписей: первое значение с русским текстом,
    не «см. X», если такое есть; иначе первое значение."""
    senses = [it.get(key) or it["text"] for it in items if it["kind"] == "sense"]
    for s in senses:
        body = _NUM_RE.sub("", s).strip()
        if CYR_RE.search(body) and not _REF_RE.match(body):
            return s
    return senses[0] if senses else ""


def cut_gloss(s: str) -> str:
    """Короткая подпись из полного значения: без нумерации, не длиннее 80 символов.
    Русский и узбекский режутся одинаково — узбекский берётся из перевода полной строки,
    а не переводится отдельно обрезанным (модель «дописывала» обрезанное)."""
    s = _NUM_RE.sub("", s or "").strip()
    return s if len(s) <= 80 else s[:80].rsplit(" ", 1)[0] + "…"


def short(items: list[dict], key: str = "text") -> str:
    """Короткое значение для списков."""
    return cut_gloss(first_sense(items, key))


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


def sense_for(entry: BkrsEntry, pinyin: str | None = None) -> str:
    """Полное первое значение статьи; если задано чтение и в статье их несколько —
    значение именно этого чтения ("" — если такого чтения в статье нет)."""
    readings, items = parsed(entry)
    if not has_russian(items):
        return ""
    own = entry_readings(entry, items)
    if not pinyin or len(own) <= 1:
        return first_sense(items)
    by = dsl.assign_readings(items, readings, own)  # строки по чтениям самой статьи
    key = dsl.match_reading(pinyin.split(",")[0].strip(), list(by))
    return first_sense(by[key]) if key else ""


def short_for(entry: BkrsEntry, pinyin: str | None = None) -> str:
    return cut_gloss(sense_for(entry, pinyin))


async def _to_uz(session: AsyncSession, svc: Services, texts: list[str]) -> dict[str, str]:
    """Перевод ru→uz того, что можно: кэш + сервис; недоступное/негодное — отсутствует."""
    uniq = list(dict.fromkeys(t for t in texts if t))
    if not uniq or not svc.translator or not (await svc.available(session))["translate"]:
        return {}
    try:
        out = await svc.translator.translate(session, uniq, "ru", "uz", partial=True)
    except TranslationUnavailable:
        return {}
    return {t: u for t, u in zip(uniq, out) if u}


def _src_text(it: dict) -> str:
    return it["tr"] if it["kind"] == "ex" else it["text"]


async def translate_items(session: AsyncSession, svc: Services, groups: list[list[dict]],
                          lang: str) -> list[str]:
    """Готовит строки к показу на языке lang (по строке: переведённые — по-узбекски,
    остальные — по-русски). Возвращает вид источника для каждой группы (чтения):
    bkrs | bkrs_mt | bkrs_part | bkrs_ru."""
    if lang != "uz":
        return ["bkrs"] * len(groups)
    done = await _to_uz(session, svc, [_src_text(it) for items in groups for it in items])
    kinds = []
    for items in groups:
        texts = [t for t in map(_src_text, items) if t]
        hit = sum(1 for t in texts if t in done)
        kinds.append("bkrs" if not texts else "bkrs_mt" if hit == len(texts)
                     else "bkrs_part" if hit else "bkrs_ru")
        for it in items:
            if it["kind"] == "ex":
                if it["tr"] in done:
                    it["tr"] = done[it["tr"]]
                    it["text"] = f"{it['zh']} {it['tr']}".strip()
            elif it["text"] in done:
                it["text"] = done[it["text"]]
    return kinds


async def apply_short_glosses(session: AsyncSession, svc: Services, rows: list[dict],
                              lang: str, key: str = "zh") -> None:
    """Короткие значения БКРС для списков (разбор фразы по словам, кандидаты, словосочетания).
    Меняет rows на месте.

    ru — значение БКРС всегда (как на сайте).
    uz — значение редакции (человеческий узбекский) не трогаем; остальное — перевод полной
         строки значения, обрезанный так же, как русский; если перевода нет — русский БКРС
         (gloss_kind bkrs_ru) вместо английского CC-CEDICT; узбекский Wiktionary оставляем."""
    if lang not in ("ru", "uz") or not rows:
        return
    if lang == "uz":
        rows = [r for r in rows if r.get("gloss_kind") != "curated"]
    entries = await find(session, (r[key] for r in rows))
    # полное значение того чтения, что показано в строке (кандидат «yú», словосочетание)
    full: dict[int, str] = {}
    for i, r in enumerate(rows):
        e = entries.get(r[key])
        s = sense_for(e, r.get("pinyin")) if e else ""
        if s:
            full[i] = s
    if not full:
        return
    if lang == "ru":
        for i, s in full.items():
            rows[i]["gloss"], rows[i]["gloss_kind"] = cut_gloss(s), "bkrs"
        return
    done = await _to_uz(session, svc, list(full.values()))
    for i, s in full.items():
        r = rows[i]
        if s in done:
            r["gloss"], r["gloss_kind"] = cut_gloss(done[s]), "bkrs_mt"
        elif r.get("gloss_kind") in ("cedict_en", "", "_bkrs_only"):
            r["gloss"], r["gloss_kind"] = cut_gloss(s), "bkrs_ru"
