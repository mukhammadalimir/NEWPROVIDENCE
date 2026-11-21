"""Импорт CC-CEDICT в таблицу dict_entries (source="cedict").

CC-CEDICT — китайско-английский словарь, лицензия CC BY-SA 4.0 (https://cc-cedict.org).
Источник указывается в интерфейсе. Частоты слов — из словаря jieba (MIT).

Использование:
  python -m app.scripts.import_cedict --url https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz
  python -m app.scripts.import_cedict --file cedict_ts.u8      # или .gz, или cedict.json (npm cedict-json)
"""

import argparse
import asyncio
import gzip
import io
import json
import re
import urllib.request

import jieba
from sqlalchemy import delete, insert

from app.db import SessionLocal
from app.models import DictEntry
from app.text.pinyin import keys_from_numbered

LINE_RE = re.compile(r"^(\S+) (\S+) \[([^\]]*)\] /(.*)/\s*$")
CL_ANY_RE = re.compile(r"\(?CL:([^)/]+)\)?")


def parse_u8(text: str):
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        m = LINE_RE.match(line)
        if m:
            trad, simp, pin, defs = m.groups()
            yield trad, simp, pin, defs.split("/")


def parse_json(data: list[dict]):
    for e in data:
        yield e["traditional"], e["simplified"], e["pinyin"], e["english"]


def measure_word(defs: list[str]) -> tuple[list[str], str | None]:
    """"CL:條|条[tiao2]" → "条 (tiáo)"; убирает счётные слова из текста определений.

    Встречается как отдельное определение "CL:..." и внутри: "fish (CL:條|条[tiao2])".
    """
    from app.text.pinyin import numbered_to_marks

    out, cls = [], []
    for d in defs:
        for m in CL_ANY_RE.finditer(d):
            for item in m.group(1).split(","):
                mm = re.match(r"(?:[^|\[]+\|)?([^\[]+)\[([^\]]+)\]", item.strip())
                if mm:
                    label = f"{mm.group(1)} ({numbered_to_marks(mm.group(2))})"
                    if label not in cls:
                        cls.append(label)
        d = CL_ANY_RE.sub("", d).replace("()", "").strip(" ;,")
        if d:
            out.append(d)
    return out, (", ".join(cls) or None)


def load_freq() -> dict[str, int]:
    freq = {}
    with jieba.dt.get_dict_file() as f:
        for raw in f:
            parts = raw.decode("utf-8").split()
            if len(parts) >= 2:
                freq[parts[0]] = int(parts[1])
    return freq


def read_source(args) -> bytes:
    if args.url:
        with urllib.request.urlopen(args.url, timeout=120) as r:
            return r.read()
    with open(args.file, "rb") as f:
        return f.read()


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file")
    ap.add_argument("--url")
    args = ap.parse_args()
    if not (args.file or args.url):
        ap.error("нужен --file или --url")
    raw = read_source(args)
    name = (args.url or args.file).lower()
    if name.endswith(".gz"):
        raw = gzip.decompress(raw)
    rows_iter = (parse_json(json.loads(raw)) if name.endswith(".json")
                 else parse_u8(io.TextIOWrapper(io.BytesIO(raw), "utf-8").read()))

    freq = load_freq()
    batch, total = [], 0
    async with SessionLocal() as session:
        await session.execute(delete(DictEntry).where(DictEntry.source == "cedict"))
        for trad, simp, pin, defs in rows_iter:
            defs, cl = measure_word([d for d in defs if d])
            tone_key, key = keys_from_numbered(pin)
            batch.append({
                "source": "cedict", "simplified": simp[:64], "traditional": trad[:64],
                "pinyin_num": pin[:128], "pinyin_tone_key": tone_key[:128],
                "pinyin_key": key[:128], "senses": [{"en": defs}], "measure_word": cl,
                "usage": {}, "collocations": [], "examples": [], "verified": False,
                "freq": freq.get(simp, 0),
            })
            if len(batch) >= 5000:
                await session.execute(insert(DictEntry), batch)
                total += len(batch)
                batch = []
        if batch:
            await session.execute(insert(DictEntry), batch)
            total += len(batch)
        await session.commit()
    print(f"CC-CEDICT: импортировано {total} статей")


if __name__ == "__main__":
    asyncio.run(main())
