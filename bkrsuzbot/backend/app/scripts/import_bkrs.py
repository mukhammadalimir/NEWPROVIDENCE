"""Импорт 大БКРС (bkrs.info) — человеческого китайско-русского словаря — в таблицу bkrs_entries.

bkrs.info публикует свежую базу каждый день (формат DSL):
  https://bkrs.info/downloads/daily/dabkrs_YYMMDD.gz
«Базы можно использовать свободно в любых целях. Можно указать данный сайт как источник.»
(https://bkrs.info/p47). Источник «大БКРС, bkrs.info» показывается в карточке.

Использование:
  python -m app.scripts.import_bkrs                 # скачать свежую базу (последние 7 дней)
  python -m app.scripts.import_bkrs --file dabkrs_261122.gz
Повторный запуск заменяет данные целиком (~3,5 млн статей, несколько минут).
"""

import argparse
import asyncio
import gzip
import io
import sys
import urllib.request
from collections.abc import Iterable, Iterator
from datetime import date, timedelta

from sqlalchemy import delete, insert, text

from app.db import IS_SQLITE, SessionLocal, engine
from app.models import BkrsEntry

DAILY_URL = "https://bkrs.info/downloads/daily/dabkrs_{d:%y%m%d}.gz"
UA = "Mozilla/5.0 (bkrsuzbot dictionary import)"
MAX_HEADWORD = 255
MAX_PINYIN = 512
BATCH = 20000


def parse_dsl(lines: Iterable[str]) -> Iterator[tuple[str, str, str]]:
    """(иероглифы, пиньинь, тело DSL) для каждой статьи.

    Формат BKRS: строка заголовка без отступа, затем строка пиньиня с отступом
    (может отсутствовать), затем тело с отступом ([m1]…[/m]…)."""
    head: str | None = None
    body: list[str] = []

    def flush():
        if head is None or not body:
            return None
        if "[" in body[0]:  # статья без пиньиня
            pinyin, rest = "", body
        else:
            pinyin, rest = body[0], body[1:]
        rest = [x for x in rest if x and x != "_"]
        if not rest:
            return None
        return head, pinyin, "\n".join(rest)

    for raw in lines:
        line = raw.rstrip("\r\n")
        if line.startswith("﻿"):
            line = line[1:]
        if not line.strip() or (line.startswith("#") and head is None):
            continue
        if not line[0].isspace():
            item = flush()
            if item:
                yield item
            head, body = line.strip(), []
        elif head is not None:
            body.append(line.strip())
    item = flush()
    if item:
        yield item


def open_source(file: str | None, url: str | None) -> io.TextIOBase:
    if file:
        return gzip.open(file, "rt", encoding="utf-8", errors="replace")
    urls = [url] if url else [DAILY_URL.format(d=date.today() - timedelta(days=i)) for i in range(7)]
    last: Exception | None = None
    for u in urls:
        try:
            resp = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}),
                                          timeout=60)
            print("Скачивание:", u, flush=True)
            return io.TextIOWrapper(gzip.GzipFile(fileobj=resp), encoding="utf-8", errors="replace")
        except Exception as e:  # 404 для ещё не выложенной базы — пробуем предыдущий день
            last = e
    raise SystemExit(f"Не удалось скачать базу 大БКРС: {last}")


async def run(src: io.TextIOBase) -> int:
    total = 0
    async with SessionLocal() as session:
        await session.execute(delete(BkrsEntry))
        if IS_SQLITE:  # без индекса вставка в разы быстрее
            await session.execute(text("DROP INDEX IF EXISTS ix_bkrs_headword"))
        rows: list[dict] = []
        for hw, pinyin, body in parse_dsl(src):
            if len(hw) > MAX_HEADWORD:
                continue
            rows.append({"headword": hw, "pinyin": pinyin[:MAX_PINYIN], "body": body})
            if len(rows) >= BATCH:
                await session.execute(insert(BkrsEntry), rows)
                total += len(rows)
                rows = []
                if total % 500000 == 0:
                    print(f"  {total:,}", flush=True)
        if rows:
            await session.execute(insert(BkrsEntry), rows)
            total += len(rows)
        if IS_SQLITE:
            await session.execute(text("CREATE INDEX ix_bkrs_headword ON bkrs_entries (headword)"))
        await session.commit()
    if IS_SQLITE:
        async with engine.connect() as conn:
            await conn.execute(text("ANALYZE"))
    await engine.dispose()
    return total


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="локальный dabkrs_*.gz")
    ap.add_argument("--url", help="адрес базы (по умолчанию — свежая ежедневная)")
    a = ap.parse_args()
    with open_source(a.file, a.url) as src:
        n = asyncio.run(run(src))
    print(f"大БКРС: импортировано {n:,} статей")


if __name__ == "__main__":
    main()
