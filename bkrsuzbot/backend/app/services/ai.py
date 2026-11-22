"""AI-пояснения и примеры. Необязательная функция.

- AIExplainer — Claude API (платно, ANTHROPIC_API_KEY).
- GeminiExplainer — Gemini API (бесплатный ключ AI Studio, GEMINI_API_KEY).

Всё, что возвращает этот модуль, в интерфейсе помечается как «создано AI» —
это не словарные данные. Пиньинь для примеров считаем сами (pypinyin),
а не доверяем модели. Ответы кэшируются.
"""

import hashlib
import json
import logging

import anthropic
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CacheItem
from app.services.events import log_event

log = logging.getLogger(__name__)

LANG_NAMES = {"uz": "Uzbek (Latin script)", "ru": "Russian"}
SYSTEM = ("You are a careful Chinese language teacher. Answer only in the "
          "requested JSON format, in the learner's language.")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

SCHEMA = {
    "type": "object",
    "properties": {
        "known": {"type": "boolean"},
        "usage": {"type": "string"},
        "examples": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "zh": {"type": "string"},
                    "translation": {"type": "string"},
                },
                "required": ["zh", "translation"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["known", "usage", "examples"],
    "additionalProperties": False,
}

# Та же схема в формате Gemini (OpenAPI-подмножество, без additionalProperties).
GEMINI_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "known": {"type": "BOOLEAN"},
        "usage": {"type": "STRING"},
        "examples": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {"zh": {"type": "STRING"}, "translation": {"type": "STRING"}},
                "required": ["zh", "translation"],
            },
        },
    },
    "required": ["known", "usage", "examples"],
}


class AIUnavailable(Exception):
    pass


def build_prompt(headword: str, pinyin: str, meanings: list[str], lang: str) -> str:
    return (
        f"Chinese word: {headword}\nReading (pinyin): {pinyin}\n"
        f"Dictionary meanings for THIS reading: {'; '.join(meanings) or 'unknown'}\n\n"
        f"Write for a learner whose language is {LANG_NAMES[lang]}:\n"
        "1. usage: 1-3 short sentences on where and how this word is used "
        "(register, typical contexts, common mistakes). Only for this reading.\n"
        "2. examples: 2-3 short, natural, everyday Chinese sentences (simplified "
        "characters) that use the word in this reading, each with a translation.\n"
        "If you are not confident about this word or reading, set known=false, "
        "usage to an empty string and examples to an empty list. Do not invent meanings."
    )


def _valid(data) -> bool:
    return (isinstance(data, dict) and isinstance(data.get("known"), bool)
            and isinstance(data.get("usage"), str) and isinstance(data.get("examples"), list)
            and all(isinstance(e, dict) and isinstance(e.get("zh"), str)
                    and isinstance(e.get("translation"), str) for e in data["examples"]))


class _CachedExplainer:
    model = ""

    async def _call(self, session: AsyncSession, prompt: str) -> dict:
        raise NotImplementedError

    async def _fail(self, session: AsyncSession, reason: str) -> AIUnavailable:
        await log_event(session, "ai", False, reason)
        await session.commit()
        return AIUnavailable(reason)

    async def explain(self, session: AsyncSession, headword: str, pinyin: str,
                      meanings: list[str], lang: str) -> dict:
        """Краткое пояснение употребления + 2–3 примера для конкретного чтения слова."""
        key = hashlib.sha256(
            f"ai|{self.model}|{lang}|{headword}|{pinyin}|{'/'.join(meanings)}".encode()
        ).hexdigest()
        cached = await session.get(CacheItem, key)
        if cached:
            return cached.value

        data = await self._call(session, build_prompt(headword, pinyin, meanings, lang))
        if not _valid(data):
            raise await self._fail(session, "bad json")
        session.add(CacheItem(key=key, kind="ai", value=data))
        await log_event(session, "ai", True, headword)
        await session.commit()
        return data


class AIExplainer(_CachedExplainer):
    """Claude API (платно)."""

    def __init__(self, api_key: str, model: str):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model

    async def _call(self, session: AsyncSession, prompt: str) -> dict:
        try:
            response = await self.client.beta.messages.create(
                model=self.model,
                max_tokens=4000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={
                    "effort": "medium",
                    "format": {"type": "json_schema", "schema": SCHEMA},
                },
                system=SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.RateLimitError as e:
            raise await self._fail(session, "rate limit") from e
        except anthropic.APIStatusError as e:
            raise await self._fail(session, f"http {e.status_code}") from e
        except anthropic.APIConnectionError as e:
            raise await self._fail(session, "network") from e

        if response.stop_reason in ("refusal", "max_tokens"):
            raise await self._fail(session, str(response.stop_reason))
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise await self._fail(session, "bad json") from e


class GeminiExplainer(_CachedExplainer):
    """Gemini API: бесплатный ключ https://aistudio.google.com/apikey (лимиты бесплатного тарифа)."""

    def __init__(self, api_key: str, model: str, http: httpx.AsyncClient):
        self.api_key = api_key
        self.model = model
        self.http = http

    async def _call(self, session: AsyncSession, prompt: str) -> dict:
        body = {
            "systemInstruction": {"parts": [{"text": SYSTEM}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.3,
                "responseMimeType": "application/json",
                "responseSchema": GEMINI_SCHEMA,
            },
        }
        try:
            r = await self.http.post(GEMINI_URL.format(model=self.model), json=body,
                                     headers={"x-goog-api-key": self.api_key}, timeout=30)
        except httpx.HTTPError as e:
            raise await self._fail(session, "network") from e
        if r.status_code == 429:
            raise await self._fail(session, "rate limit")
        if r.status_code != 200:
            raise await self._fail(session, f"http {r.status_code}")
        try:
            parts = r.json()["candidates"][0]["content"]["parts"]
            return json.loads("".join(p.get("text", "") for p in parts))
        except (KeyError, IndexError, ValueError) as e:
            raise await self._fail(session, "bad json") from e
