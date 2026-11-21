"""AI-пояснения и примеры (Claude API). Необязательная функция.

Всё, что возвращает этот модуль, в интерфейсе помечается как «создано AI» —
это не словарные данные. Пиньинь для примеров считаем сами (pypinyin),
а не доверяем модели. Ответы кэшируются.
"""

import hashlib
import json
import logging

import anthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CacheItem
from app.services.events import log_event

log = logging.getLogger(__name__)

LANG_NAMES = {"uz": "Uzbek (Latin script)", "ru": "Russian"}

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


class AIUnavailable(Exception):
    pass


class AIExplainer:
    def __init__(self, api_key: str, model: str):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model

    async def explain(self, session: AsyncSession, headword: str, pinyin: str,
                      meanings: list[str], lang: str) -> dict:
        """Краткое пояснение употребления + 2–3 примера для конкретного чтения слова."""
        key = hashlib.sha256(
            f"ai|{self.model}|{lang}|{headword}|{pinyin}|{'/'.join(meanings)}".encode()
        ).hexdigest()
        cached = await session.get(CacheItem, key)
        if cached:
            return cached.value

        prompt = (
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
                system="You are a careful Chinese language teacher. Answer only in the "
                       "requested JSON format, in the learner's language.",
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.RateLimitError as e:
            await log_event(session, "ai", False, "rate limit")
            await session.commit()
            raise AIUnavailable("rate limit") from e
        except anthropic.APIStatusError as e:
            await log_event(session, "ai", False, f"http {e.status_code}")
            await session.commit()
            raise AIUnavailable(f"http {e.status_code}") from e
        except anthropic.APIConnectionError as e:
            await log_event(session, "ai", False, "network")
            await session.commit()
            raise AIUnavailable("network") from e

        if response.stop_reason in ("refusal", "max_tokens"):
            await log_event(session, "ai", False, str(response.stop_reason))
            await session.commit()
            raise AIUnavailable(str(response.stop_reason))
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            await log_event(session, "ai", False, "bad json")
            await session.commit()
            raise AIUnavailable("bad json") from e

        session.add(CacheItem(key=key, kind="ai", value=data))
        await log_event(session, "ai", True, headword)
        await session.commit()
        return data
