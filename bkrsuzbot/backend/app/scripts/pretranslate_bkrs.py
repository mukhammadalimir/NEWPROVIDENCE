"""Заранее перевести строки 大БКРС на узбекский (Gemini), чтобы автономная Mini App
показывала узбекский: у неё нет сервера, и ключ Gemini в неё класть нельзя.

Переводятся ровно те строки, что попадают в Mini App (export_offline.collect_articles),
начиная с самых частотных слов. Результат — в кэше перевода (cache_items): его же
использует бот, а export_offline добавляет узбекские строки в data/bkrs/*.json.

  python -m app.scripts.pretranslate_bkrs --words 3000      # первые 3000 частотных слов
  python -m app.scripts.pretranslate_bkrs                   # все (несколько дней на бесплатном ключе)
  python -m app.scripts.export_offline --out ../webapp/data  # затем — в Mini App

Можно прервать (Ctrl+C) и запустить снова: уже переведённое берётся из кэша.
Бесплатный ключ Gemini ограничен по запросам в минуту и в день: при 429 скрипт ждёт,
а если лимит не отпускает — останавливается («продолжите завтра»).
"""

import argparse
import asyncio
import sys
import time

import httpx
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal, engine
from app.models import CacheItem, DictEntry
from app.scripts.export_offline import (MT_PROVIDERS, _mt_key, article_strings,
                                       collect_articles, uz_cache)
from app.services.translate import (GeminiTranslator, TranslationUnavailable,
                                    fix_uz_numbering, uz_problem)
from app.text import uzbek


class Stop(Exception):
    """Дальше переводить нельзя (дневной лимит, неверный ключ)."""


class Runner:
    def __init__(self, key: str, models: list[str], rpm: float, http: httpx.AsyncClient):
        self.translators = [GeminiTranslator(key, m, http, timeout=120) for m in models]
        self.current = 0
        self.min_gap = 60.0 / rpm
        self.last = 0.0
        self.lock = asyncio.Lock()  # общий темп для всех параллельных запросов
        self.requests = self.skipped = 0
        # подряд неудачных запросов (по всем моделям) и полных кругов без успеха
        self.fail_streak = 0
        self.limit_rounds = self.busy_rounds = 0

    @property
    def tr(self) -> GeminiTranslator:
        return self.translators[self.current]

    async def _next_model(self, msg: str, limited: bool):
        """Модель перегружена или упёрлась в лимит — следующая (лимиты бесплатного ключа
        у каждой модели свои). Если не отвечает ни одна — пауза 30 с … 5 мин."""
        self.fail_streak += 1
        self.current = (self.current + 1) % len(self.translators)
        if self.fail_streak < len(self.translators):
            return
        self.fail_streak = 0
        if limited:
            self.limit_rounds += 1
            if self.limit_rounds >= 6:
                raise Stop("лимит бесплатного ключа Gemini исчерпан у всех моделей — "
                           "продолжите позже (завтра), уже переведённое сохранено")
        else:
            self.busy_rounds += 1
            if self.busy_rounds >= 16:  # ~1 час без ответа
                raise Stop(f"Gemini долго недоступен ({msg[:100]}) — попробуйте позже")
        wait = min(300, 30 * 2 ** (self.limit_rounds + self.busy_rounds - 1))
        print(f"  все модели: {msg[:50]!r} — жду {wait} с…", flush=True)
        await asyncio.sleep(wait)

    async def _pace(self):
        async with self.lock:
            wait = self.last + self.min_gap - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self.last = time.monotonic()

    async def translate(self, batch: list[str]) -> int:
        """Переводит пакет (результат сохраняется в кэш). Возвращает число переведённых строк."""
        while True:
            await self._pace()
            self.requests += 1
            try:
                async with SessionLocal() as s:
                    await self.tr.translate(s, batch, "ru", "uz")
                self.fail_streak = self.limit_rounds = self.busy_rounds = 0
                return len(batch)
            except TranslationUnavailable as e:
                msg = str(e)
            if "http 404" in msg:  # модель убрали — больше не пробуем
                if len(self.translators) == 1:
                    raise Stop(f"модель {self.tr.model} недоступна ({msg[:100]})")
                print(f"  модель {self.tr.model} недоступна — убираю", flush=True)
                del self.translators[self.current]
                self.current %= len(self.translators)
            elif any(f"http {c}" in msg for c in (400, 401, 403)):
                raise Stop(f"Gemini отклонил запрос ({msg[:160]}). Проверьте GEMINI_API_KEY.")
            elif "bad response" in msg:
                if len(batch) == 1:
                    self.skipped += 1
                    return 0
                mid = len(batch) // 2  # модель сбилась со счётом — делим пакет пополам
                return await self.translate(batch[:mid]) + await self.translate(batch[mid:])
            else:  # 429 (лимит), 5xx и сеть (перегрузка) — следующая модель
                await self._next_model(msg, limited="http 429" in msg)


async def recheck(texts: list[str]) -> tuple[int, int]:
    """Уже сохранённые переводы ru→uz этих строк: апострофы — к единому виду
    (uzbek.typographic), негодные по uz_problem (кириллица, потерянные иероглифы, номера…) —
    удалить из кэша, чтобы следующий запуск перевёл их заново. (исправлено, удалено)"""
    by_key = {_mt_key(p, t): t for t in texts for p in MT_PROVIDERS}
    fixed = dropped = 0
    keys = list(by_key)
    async with SessionLocal() as s:
        for i in range(0, len(keys), 500):
            for c in (await s.scalars(select(CacheItem).where(
                    CacheItem.key.in_(keys[i:i + 500])))).all():
                src, value = by_key[c.key], (c.value or {}).get("text", "")
                if uz_problem(src, value):
                    await s.delete(c)
                    dropped += 1
                    continue
                good = uzbek.typographic(fix_uz_numbering(value))
                if good != value:
                    c.value = {"text": good}
                    fixed += 1
            await s.commit()
    return fixed, dropped


def batches(texts: list[str], size: int, max_chars: int):
    cur, chars = [], 0
    for t in texts:
        if cur and (len(cur) >= size or chars + len(t) > max_chars):
            yield cur
            cur, chars = [], 0
        cur.append(t)
        chars += len(t)
    if cur:
        yield cur


async def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    st = get_settings()
    ap = argparse.ArgumentParser()
    ap.add_argument("--words", type=int, default=0, help="сколько самых частотных слов (0 — все)")
    ap.add_argument("--batch", type=int, default=100, help="строк в одном запросе")
    ap.add_argument("--max-chars", type=int, default=9000, help="символов в одном запросе")
    ap.add_argument("--rpm", type=float, default=10, help="запросов в минуту (бесплатный ключ — ~10–15)")
    ap.add_argument("--workers", type=int, default=3,
                    help="параллельных запросов (ответ идёт 10–20 с; общий темп — --rpm)")
    # модель бота (GEMINI_MODEL) — последней: лимиты ключа у каждой модели свои, и
    # заблаговременный перевод не должен съедать дневной лимит живого бота
    rotation = [m for m in ("gemini-3.1-flash-lite", "gemini-3.5-flash-lite",
                            "gemini-flash-latest", "gemini-flash-lite-latest")
                if m != st.gemini_model] + [st.gemini_model]
    ap.add_argument("--models", default=",".join(rotation),
                    help="модели по очереди: при перегрузке или лимите — следующая "
                         "(у бесплатного ключа лимиты у каждой модели свои)")
    ap.add_argument("--recheck", action="store_true",
                    help="проверить уже переведённое (uz_problem), привести апострофы к единому "
                         "виду, негодное удалить из кэша — оно переведётся заново")
    a = ap.parse_args()
    if not st.gemini_api_key:
        print("GEMINI_API_KEY не задан (backend/.env). Ключ: https://aistudio.google.com/apikey")
        return 1

    async with SessionLocal() as s:
        rows = list((await s.scalars(select(DictEntry).order_by(DictEntry.id))).all())
        print("Сбор строк БКРС…", flush=True)
        articles = await collect_articles(s, rows)
        done_uz = await uz_cache(s)
    freq: dict[str, int] = {}
    for e in rows:
        freq[e.simplified] = max(freq.get(e.simplified, 0), e.freq or 0)
    heads = sorted(articles, key=lambda h: -freq.get(h, 0))
    if a.words:
        heads = heads[:a.words]
    texts = list(dict.fromkeys(t for h in heads for t in article_strings(articles[h])))
    if a.recheck:
        fixed, dropped = await recheck(texts)
        print(f"Проверка кэша: апострофы исправлены у {fixed}, негодных удалено {dropped}",
              flush=True)
        async with SessionLocal() as s:
            done_uz = await uz_cache(s)
    todo = [t for t in texts if not done_uz(t)]
    print(f"Слов: {len(heads)}, строк: {len(texts)}, уже переведено: {len(texts) - len(todo)}, "
          f"осталось: {len(todo)} ({sum(map(len, todo)) / 1e6:.1f} млн символов)", flush=True)

    models = list(dict.fromkeys(m.strip() for m in a.models.split(",") if m.strip()))
    t0 = time.monotonic()
    state = {"done": 0, "batches": 0, "stop": None}
    queue: asyncio.Queue = asyncio.Queue()
    for b in batches(todo, a.batch, a.max_chars):
        queue.put_nowait(b)

    async def worker(run: Runner):
        while not state["stop"] and not queue.empty():
            batch = queue.get_nowait()
            try:
                # не «state["done"] += await …»: значение читается до await, и параллельные
                # работники затирают прибавки друг друга
                n = await run.translate(batch)
                state["done"] += n
            except Stop as e:
                state["stop"] = str(e)
                return
            state["batches"] += 1
            if state["batches"] % 5 == 0 or queue.empty():
                rate = state["done"] / max(time.monotonic() - t0, 1)
                eta = (len(todo) - state["done"]) / rate / 60 if rate else 0
                print(f"  {state['done']}/{len(todo)} строк, запросов {run.requests}, "
                      f"модель {run.tr.model}, осталось ~{eta:.0f} мин", flush=True)

    async with httpx.AsyncClient() as http:
        run = Runner(st.gemini_api_key, models, a.rpm, http)
        try:
            await asyncio.gather(*(worker(run) for _ in range(max(1, a.workers))))
        except (KeyboardInterrupt, asyncio.CancelledError):
            print("Прервано — переведённое сохранено.", flush=True)
    if state["stop"]:
        print(f"Остановлено: {state['stop']}", flush=True)
    await engine.dispose()
    print(f"Готово: переведено {state['done']} строк, пропущено {run.skipped}, "
          f"запросов {run.requests}. Дальше: python -m app.scripts.export_offline "
          "--out ../webapp/data", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
