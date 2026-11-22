"""Экспорт словаря для автономной Mini App (GitHub Pages, без сервера).

  python -m app.scripts.export_offline --out ../webapp/data

cedict.json — CC-CEDICT (CC BY-SA 4.0, https://cc-cedict.org): [упр., трад., пиньинь, опр., счётн., частота]
meta.json   — слоги пиньиня и редакционные карточки (uz/ru).
bkrs/N.json — статьи 大БКРС (bkrs.info) для слов словаря, разбитые на части по хэшу написания
              (телефон скачивает только нужную часть). Строки уже распределены по чтениям
              карточки; узбекский перевод — из кэша машинного перевода бота, если он есть.
"""

import argparse
import asyncio
import hashlib
import json
import shutil
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import select

from app.db import SessionLocal
from app.models import CacheItem, DictEntry
from app.services import bkrs
from app.text import dsl
from app.text.pinyin import keys_from_numbered, syllables, word_marks

BKRS_SHARDS = 1024
KIND_CODE = {"head": 0, "sense": 1, "ex": 2}
MT_PROVIDERS = ("gemini", "google")


def shard_of(headword: str, n: int = BKRS_SHARDS) -> int:
    """Тот же хэш, что в miniapp/src/offline/engine.ts (bkrsShard)."""
    x = 0
    for ch in headword:
        x = (x * 31 + ord(ch)) & 0xFFFFFFFF
    return x % n


def reading_key(pinyin_num: str) -> str:
    """Ключ чтения как в engine.ts: `${toneKey}|${isProper}`."""
    proper = "true" if pinyin_num[:1] != pinyin_num[:1].lower() else "false"
    return f"{keys_from_numbered(pinyin_num)[0]}|{proper}"


def _mt_key(provider: str, text: str) -> str:
    return hashlib.sha256(f"mt|{provider}|ru|uz|{text}".encode()).hexdigest()


async def uz_cache(session) -> Callable[[str], str | None]:
    """Узбекские переводы строк БКРС, которые уже есть в кэше (бот или pretranslate_bkrs)."""
    cache = {c.key: (c.value or {}).get("text") for c in (await session.scalars(
        select(CacheItem).where(CacheItem.kind == "mt"))).all()}

    def uz(text: str) -> str | None:
        for p in MT_PROVIDERS:
            v = cache.get(_mt_key(p, text))
            if v:
                return v
        return None
    return uz


def article_strings(art: dict) -> list[str]:
    """Все русские строки статьи, которые показываются в Mini App (для перевода на uz)."""
    out = []
    for lines in art["r"].values():
        for line in lines:
            t = line[2] if line[0] == 2 else line[1]
            if t:
                out.append(t)
    # короткие подписи g/gp берутся из перевода ПОЛНЫХ строк значений (не обрезанных)
    out.extend(art.get("_full", []))
    return out


async def collect_articles(session, rows: list[DictEntry],
                           uz: Callable[[str], str | None] = lambda t: None) -> OrderedDict:
    """Статьи БКРС для всех написаний словаря:
    {написание: {"r": {ключ чтения: строки}, "o": порядок чтений как в БКРС,
                 "g": короткое значение (ru), "gu": то же на узбекском, если переведено,
                 "gp": {чтение: [ru, uz?]}}}.
    Строка: [0 заголовок | 1 значение, текст, uz?] или [2, пример zh, перевод ru, uz?]."""
    readings: OrderedDict[str, OrderedDict[str, str]] = OrderedDict()
    # тот же порядок чтений, что у карточки (dictionary.py, engine.ts): редакция, обычные,
    # имена собственные последними — иначе статья 王 достанется фамилии Wáng
    for e in sorted(rows, key=lambda e: (e.source != "curated",
                                         e.pinyin_num[:1] != e.pinyin_num[:1].lower(), e.id)):
        readings.setdefault(e.simplified, OrderedDict()).setdefault(
            reading_key(e.pinyin_num), word_marks(e.pinyin_num))
    found = await bkrs.find(session, list(readings))
    articles: OrderedDict[str, dict] = OrderedDict()
    for head, keys in readings.items():
        e = found.get(head)
        if not e:
            continue
        entry_rd, items = bkrs.parsed(e)
        if not bkrs.has_russian(items):  # статья БКРС без русского — оставляем CC-CEDICT
            continue
        by_pinyin = dsl.assign_readings(items, entry_rd, list(keys.values()))
        art: dict = {"r": {}}
        full: dict[str, str] = {}  # полное первое значение по чтениям (для подписей)
        for key, pinyin in keys.items():
            # в Mini App ограничения Telegram нет — почти вся статья
            sel = bkrs.select_items(by_pinyin.get(pinyin, []), bkrs.OFFLINE_MAX_ITEMS,
                                    bkrs.OFFLINE_MAX_CHARS)
            if not sel or not bkrs.has_russian(sel):
                continue
            if s := bkrs.first_sense(sel):
                full[pinyin] = s
            lines = []
            for it in sel:
                if it["kind"] == "ex":
                    line = [2, it["zh"], it["tr"]]
                    u = uz(it["tr"]) if it["tr"] else None
                else:
                    line = [KIND_CODE[it["kind"]], it["text"]]
                    u = uz(it["text"])
                if u:
                    line.append(u)
                lines.append(line)
            art["r"][key] = lines
        if not art["r"]:
            continue
        # порядок всех чтений карточки (как на сервере), а не только тех, где есть строки
        order = [dsl.norm_pinyin(x) for x in bkrs.entry_readings(e, items)]
        art["o"] = sorted(keys, key=lambda k: order.index(dsl.norm_pinyin(keys[k]))
                          if dsl.norm_pinyin(keys[k]) in order else len(order))
        # короткие подписи: из полного значения, обрезанного одинаково для ru и uz
        # (узбекский — перевод полной строки; отдельно обрезанное модель «дописывала»)
        first = next((full[keys[k]] for k in art["o"] if keys[k] in full), None)
        first = first or bkrs.first_sense(items)
        if first:
            art["g"] = bkrs.cut_gloss(first)
            if u := uz(first):
                art["gu"] = bkrs.cut_gloss(u)
        # по чтениям карточки (кандидаты «yú», словосочетания) — из тех же строк, что в "r"
        if len(keys) > 1:
            art["gp"] = {p: [bkrs.cut_gloss(s)] + ([bkrs.cut_gloss(u)] if (u := uz(s)) else [])
                         for p, s in full.items()}
        art["_full"] = list(dict.fromkeys([first, *full.values()] if first else full.values()))
        articles[head] = art
    return articles


async def export_bkrs(session, rows: list[DictEntry], out: Path) -> int:
    """data/bkrs/N.json: статьи collect_articles() с узбекскими строками из кэша."""
    shards: dict[int, dict] = {}
    for head, art in (await collect_articles(session, rows, await uz_cache(session))).items():
        art.pop("_full", None)  # служебное (для pretranslate), в Mini App не нужно
        shards.setdefault(shard_of(head), {})[head] = art

    folder = out / "bkrs"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    digest = hashlib.sha1()
    for n, data in sorted(shards.items()):
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        (folder / f"{n}.json").write_text(text, "utf-8")
        digest.update(text.encode())
    return sum(len(d) for d in shards.values()), digest.hexdigest()


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    out = Path(ap.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    async with SessionLocal() as s:
        rows = (await s.scalars(select(DictEntry).order_by(DictEntry.id))).all()
        n_bkrs, bkrs_digest = await export_bkrs(s, list(rows), out)
    cedict = [[e.simplified, "" if e.traditional == e.simplified else e.traditional, e.pinyin_num,
               "/".join(e.senses[0].get("en", [])) if e.senses else "", e.measure_word or "", e.freq]
              for e in rows if e.source == "cedict"]
    curated = [{"simplified": e.simplified, "traditional": e.traditional, "pinyin": e.pinyin_num,
                "senses": e.senses, "measure_word": e.measure_word, "usage": e.usage,
                "collocations": e.collocations, "examples": e.examples, "verified": e.verified}
               for e in rows if e.source == "curated"]
    dump = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))  # noqa: E731
    cedict_text = dump(cedict)
    (out / "cedict.json").write_text(cedict_text, "utf-8")
    # версия данных: меняется только когда меняются сами данные. Mini App запрашивает
    # meta.json без кэша, а остальные файлы — с ?v=версия, поэтому после обновления на
    # GitHub Pages телефон не показывает старую копию (Pages разрешает кэш на 10 минут).
    version = hashlib.sha1((bkrs_digest + cedict_text).encode()).hexdigest()[:12]
    (out / "meta.json").write_text(dump({
        "version": version,
        "syllables": sorted(syllables()), "curated": curated,
        "bkrs": {"shards": BKRS_SHARDS, "entries": n_bkrs} if n_bkrs else None,
        "license": "CC-CEDICT: CC BY-SA 4.0, https://cc-cedict.org; 大БКРС: https://bkrs.info"}),
        "utf-8")
    (out / "README.txt").write_text(
        "cedict.json: CC-CEDICT, Creative Commons Attribution-ShareAlike 4.0, https://cc-cedict.org\n"
        "meta.json: BKRSUZ editorial cards (uz/ru).\n"
        "bkrs/*.json: articles of 大БКРС (https://bkrs.info), a human-edited Chinese-Russian\n"
        "  dictionary. bkrs.info: the databases may be used freely for any purpose, citing the site\n"
        "  as the source (https://bkrs.info/p47). Uzbek lines, where present, are machine\n"
        "  translations of the Russian text.\n"
        "wikt.json: ru/uz <-> zh translations from Wiktionary (en.wiktionary.org, ru.wiktionary.org),\n"
        "  CC BY-SA 4.0, extracted with wiktextract (kaikki.org); not reviewed by the editors.\n", "utf-8")
    print(f"cedict: {len(cedict)}, curated: {len(curated)}, bkrs: {n_bkrs} -> {out}")


if __name__ == "__main__":
    asyncio.run(main())
