"""Экспорт словаря для автономной Mini App (GitHub Pages, без сервера).

  python -m app.scripts.export_offline --out ../webapp/data

cedict.json — CC-CEDICT (CC BY-SA 4.0, https://cc-cedict.org): [упр., трад., пиньинь, опр., счётн., частота]
meta.json   — слоги пиньиня и редакционные карточки (uz/ru).
"""

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from app.db import SessionLocal
from app.models import DictEntry
from app.text.pinyin import syllables


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    out = Path(ap.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    async with SessionLocal() as s:
        rows = (await s.scalars(select(DictEntry).order_by(DictEntry.id))).all()
    cedict = [[e.simplified, "" if e.traditional == e.simplified else e.traditional, e.pinyin_num,
               "/".join(e.senses[0].get("en", [])) if e.senses else "", e.measure_word or "", e.freq]
              for e in rows if e.source == "cedict"]
    curated = [{"simplified": e.simplified, "traditional": e.traditional, "pinyin": e.pinyin_num,
                "senses": e.senses, "measure_word": e.measure_word, "usage": e.usage,
                "collocations": e.collocations, "examples": e.examples, "verified": e.verified}
               for e in rows if e.source == "curated"]
    dump = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))  # noqa: E731
    (out / "cedict.json").write_text(dump(cedict), "utf-8")
    (out / "meta.json").write_text(dump({
        "syllables": sorted(syllables()), "curated": curated,
        "license": "CC-CEDICT: CC BY-SA 4.0, https://cc-cedict.org"}), "utf-8")
    (out / "README.txt").write_text(
        "cedict.json: CC-CEDICT, Creative Commons Attribution-ShareAlike 4.0, https://cc-cedict.org\n"
        "meta.json: BKRSUZ editorial cards (uz/ru).\n"
        "wikt.json: ru/uz <-> zh translations from Wiktionary (en.wiktionary.org, ru.wiktionary.org),\n"
        "  CC BY-SA 4.0, extracted with wiktextract (kaikki.org); not reviewed by the editors.\n", "utf-8")
    print(f"cedict: {len(cedict)}, curated: {len(curated)} → {out}")


if __name__ == "__main__":
    asyncio.run(main())
