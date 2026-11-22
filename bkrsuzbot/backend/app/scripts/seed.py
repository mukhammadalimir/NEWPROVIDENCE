"""Загрузка стартового набора редакционных карточек (app/data/seed_entries.json).

Это НЕ полноценный узбекский словарь, а стартовый набор, подготовленный вручную
(verified=False): его нужно проверить и расширять через админ-панель.
Существующие карточки (в т.ч. исправленные админом) не перезаписываются.
"""

import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from app.db import SessionLocal
from app.models import DictEntry
from app.services.curated import save_curated
from app.text.pinyin import keys_from_numbered

SEED = Path(__file__).resolve().parent.parent / "data" / "seed_entries.json"


async def main() -> None:
    data = json.loads(SEED.read_text("utf-8"))
    added = 0
    async with SessionLocal() as session:
        for item in data:
            tone_key, _ = keys_from_numbered(item["pinyin"])
            exists = await session.scalar(select(DictEntry.id).where(
                DictEntry.source == "curated", DictEntry.simplified == item["simplified"],
                DictEntry.pinyin_tone_key == tone_key))
            if exists:
                continue
            await save_curated(session, None, item, verified=False)
            added += 1
        await session.commit()
    print(f"Редакционные карточки: добавлено {added}, всего в наборе {len(data)}")


if __name__ == "__main__":
    asyncio.run(main())
