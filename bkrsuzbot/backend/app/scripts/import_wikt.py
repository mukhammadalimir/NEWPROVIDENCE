"""Загрузка переводов Wiktionary (wikt.json из scripts/build_wikt.py) в базу.

  python -m app.scripts.import_wikt --file ../webapp/data/wikt.json
Повторный запуск заменяет данные целиком.
"""
from __future__ import annotations

import argparse
import asyncio
import json

from sqlalchemy import delete, insert

from app.db import SessionLocal
from app.models import WiktPair


async def run(path: str) -> int:
    data = json.load(open(path, encoding="utf-8"))
    rows = [
        {"lang": lang, "term": term[:64], "zh": zh, "rank": rank}
        for lang in ("ru", "uz")
        for term, zhs in data.get(lang, {}).items()
        for rank, zh in enumerate(zhs.split("|"))
        if len(zh) <= 16
    ]
    async with SessionLocal() as session:
        await session.execute(delete(WiktPair))
        for i in range(0, len(rows), 5000):
            await session.execute(insert(WiktPair), rows[i:i + 5000])
        await session.commit()
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    a = ap.parse_args()
    print("imported", asyncio.run(run(a.file)), "pairs")


if __name__ == "__main__":
    main()
