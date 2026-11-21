"""Машинный перевод: Google Cloud Translation API (v2, ключ API).

Поддерживает узбекский (uz), русский (ru), китайский (zh-CN) и английский (en).
Результаты кэшируются в таблице cache_items.
"""

import hashlib
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CacheItem
from app.services.events import log_event

log = logging.getLogger(__name__)

GOOGLE_URL = "https://translation.googleapis.com/language/translate/v2"
LANG_CODES = {"zh": "zh-CN", "uz": "uz", "ru": "ru", "en": "en"}


class TranslationUnavailable(Exception):
    """Сервис перевода не настроен или не ответил."""


class GoogleTranslator:
    name = "google"

    def __init__(self, api_key: str, http: httpx.AsyncClient):
        self.api_key = api_key
        self.http = http

    async def _call(self, texts: list[str], src: str, tgt: str) -> list[str]:
        try:
            r = await self.http.post(
                GOOGLE_URL,
                params={"key": self.api_key},
                json={"q": texts, "source": LANG_CODES[src], "target": LANG_CODES[tgt],
                      "format": "text"},
                timeout=15,
            )
        except httpx.HTTPError as e:
            raise TranslationUnavailable(f"network: {e.__class__.__name__}") from e
        if r.status_code != 200:
            raise TranslationUnavailable(f"http {r.status_code}: {r.text[:200]}")
        return [t["translatedText"] for t in r.json()["data"]["translations"]]

    async def translate(self, session: AsyncSession, texts: list[str], src: str,
                        tgt: str) -> list[str]:
        """Переводит список строк; повторные запросы берутся из кэша."""
        if not texts:
            return []
        keys = [_key(self.name, src, tgt, t) for t in texts]
        cached = {
            c.key: c.value["text"]
            for c in (await session.scalars(
                select(CacheItem).where(CacheItem.key.in_(set(keys))))).all()
        }
        missing = [(k, t) for k, t in zip(keys, texts) if k not in cached]
        if missing:
            uniq = dict(missing)
            try:
                result = await self._call(list(uniq.values()), src, tgt)
            except TranslationUnavailable as e:
                await log_event(session, "translate", False, str(e))
                raise
            for k, value in zip(uniq.keys(), result):
                cached[k] = value
                await session.merge(CacheItem(key=k, kind="mt", value={"text": value}))
            await log_event(session, "translate", True, f"{src}->{tgt} x{len(uniq)}")
            await session.commit()
        return [cached[k] for k in keys]


def _key(provider: str, src: str, tgt: str, text: str) -> str:
    return hashlib.sha256(f"mt|{provider}|{src}|{tgt}|{text}".encode()).hexdigest()
