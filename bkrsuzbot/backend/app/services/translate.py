"""Машинный перевод: Google Gemini (бесплатный ключ AI Studio) и/или
Google Cloud Translation API (v2, ключ API).

Поддерживает узбекский (uz, латиница), русский (ru), китайский (zh-CN) и английский (en).
Результаты кэшируются в таблице cache_items (отдельно для каждого провайдера).
Если заданы оба ключа — сначала Gemini, при ошибке — Cloud Translation.
"""

import hashlib
import json
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CacheItem
from app.services.events import log_event

log = logging.getLogger(__name__)

GOOGLE_URL = "https://translation.googleapis.com/language/translate/v2"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
LANG_CODES = {"zh": "zh-CN", "uz": "uz", "ru": "ru", "en": "en"}
LANG_NAMES = {"zh": "Chinese (Simplified, Mandarin)", "uz": "Uzbek (Latin script)",
              "ru": "Russian", "en": "English"}


class TranslationUnavailable(Exception):
    """Сервис перевода не настроен или не ответил."""


class CachedTranslator:
    name = ""
    label = ""

    def __init__(self, http: httpx.AsyncClient):
        self.http = http

    async def _call(self, texts: list[str], src: str, tgt: str) -> list[str]:
        raise NotImplementedError

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
                await log_event(session, "translate", False, f"{self.name}: {e}")
                raise
            for k, value in zip(uniq.keys(), result):
                cached[k] = value
                await session.merge(CacheItem(key=k, kind="mt", value={"text": value}))
            await log_event(session, "translate", True, f"{self.name} {src}->{tgt} x{len(uniq)}")
            await session.commit()
        return [cached[k] for k in keys]


class GoogleTranslator(CachedTranslator):
    name = "google"
    label = "Google Translate"

    def __init__(self, api_key: str, http: httpx.AsyncClient):
        super().__init__(http)
        self.api_key = api_key

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


GEMINI_PROMPT = """You are a professional translator for a Chinese dictionary used by Uzbek and Russian speakers.
Translate each string of the JSON array below from {src} to {tgt}.

Rules:
- Return ONLY a JSON array of strings, the same length and order as the input.
- Uzbek must be in Latin script with the letters oʻ, gʻ written as o‘ and g‘.
- Keep Chinese characters, pinyin, numbers, numbering like 1) 2) and separators (; / ,) unchanged.
- Translate dictionary glosses as short dictionary meanings, not full sentences.
- Do not add explanations, do not omit or invent meanings. Use the commonly accepted term.

Input:
{texts}"""


class GeminiTranslator(CachedTranslator):
    """Перевод через Gemini API (ключ AI Studio: https://aistudio.google.com/apikey)."""

    name = "gemini"
    label = "Google Gemini"

    def __init__(self, api_key: str, model: str, http: httpx.AsyncClient):
        super().__init__(http)
        self.api_key = api_key
        self.model = model

    async def _call(self, texts: list[str], src: str, tgt: str) -> list[str]:
        prompt = GEMINI_PROMPT.format(src=LANG_NAMES[src], tgt=LANG_NAMES[tgt],
                                      texts=json.dumps(texts, ensure_ascii=False))
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseSchema": {"type": "ARRAY", "items": {"type": "STRING"}},
            },
        }
        try:
            r = await self.http.post(GEMINI_URL.format(model=self.model), json=body,
                                     headers={"x-goog-api-key": self.api_key}, timeout=40)
        except httpx.HTTPError as e:
            raise TranslationUnavailable(f"network: {e.__class__.__name__}") from e
        if r.status_code != 200:
            raise TranslationUnavailable(f"http {r.status_code}: {r.text[:200]}")
        try:
            parts = r.json()["candidates"][0]["content"]["parts"]
            out = json.loads("".join(p.get("text", "") for p in parts))
        except (KeyError, IndexError, ValueError) as e:
            raise TranslationUnavailable(f"bad response: {e.__class__.__name__}") from e
        if (not isinstance(out, list) or len(out) != len(texts)
                or not all(isinstance(x, str) and x.strip() for x in out)):
            raise TranslationUnavailable("bad response: wrong item count")
        return [x.strip() for x in out]


class FallbackTranslator:
    """Пробует провайдеров по очереди (например, Gemini → Cloud Translation)."""

    def __init__(self, providers: list[CachedTranslator]):
        self.providers = providers
        self.label = " / ".join(p.label for p in providers)

    async def translate(self, session: AsyncSession, texts: list[str], src: str,
                        tgt: str) -> list[str]:
        err: TranslationUnavailable | None = None
        for p in self.providers:
            try:
                return await p.translate(session, texts, src, tgt)
            except TranslationUnavailable as e:
                err = e
        raise err or TranslationUnavailable("no providers")


def _key(provider: str, src: str, tgt: str, text: str) -> str:
    return hashlib.sha256(f"mt|{provider}|{src}|{tgt}|{text}".encode()).hexdigest()
