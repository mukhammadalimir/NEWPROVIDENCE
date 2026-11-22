"""Сборка внешних сервисов по переменным окружения.

Если ключ не задан, соответствующий сервис = None, и интерфейс честно сообщает,
что функция не подключена (кнопки не показываются).
"""

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import FeatureFlag
from app.services.ai import AIExplainer, GeminiExplainer
from app.services.ratelimit import RateLimiter
from app.services.translate import FallbackTranslator, GeminiTranslator, GoogleTranslator
from app.services.tts import EdgeTTS, GoogleTTS

# Функции, которыми админ может управлять (вкл/выкл).
FLAG_DEFAULTS = {"translate": True, "tts": True, "ai": True, "collocations": True}


class Services:
    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None):
        self.settings = settings
        self.http = http or httpx.AsyncClient()
        providers = []
        if settings.gemini_api_key:
            providers.append(GeminiTranslator(settings.gemini_api_key, settings.gemini_model, self.http))
        if settings.translate_key:
            providers.append(GoogleTranslator(settings.translate_key, self.http))
        self.translator = (providers[0] if len(providers) == 1
                           else FallbackTranslator(providers) if providers else None)
        self.tts = self._make_tts(settings)
        # AI: Claude (платно), если задан ключ; иначе бесплатный Gemini.
        if settings.anthropic_api_key:
            self.ai = AIExplainer(settings.anthropic_api_key, settings.ai_model)
        elif settings.gemini_api_key:
            self.ai = GeminiExplainer(settings.gemini_api_key, settings.gemini_model, self.http)
        else:
            self.ai = None
        self.search_limiter = RateLimiter(settings.rate_search_per_min, 60)
        self.tts_limiter = RateLimiter(settings.rate_tts_per_min, 60)
        self.ai_limiter = RateLimiter(settings.rate_ai_per_hour, 3600)

    def _make_tts(self, settings: Settings):
        """auto: Google, если есть ключ, иначе бесплатный edge-tts."""
        provider = settings.tts_provider.lower()
        if provider == "off":
            return None
        if provider in ("auto", "google") and settings.tts_key:
            return GoogleTTS(settings.tts_key, self.http, settings.tts_voices,
                             settings.audio_cache_dir, settings.tts_slow_rate)
        if provider in ("auto", "edge"):
            return EdgeTTS(settings.edge_voices, settings.audio_cache_dir, settings.tts_slow_rate)
        return None

    async def flags(self, session: AsyncSession) -> dict[str, bool]:
        result = dict(FLAG_DEFAULTS)
        for f in (await session.scalars(select(FeatureFlag))).all():
            if f.key in result:
                result[f.key] = f.enabled
        return result

    async def available(self, session: AsyncSession) -> dict[str, bool]:
        """Функция доступна, только если она и настроена (есть ключ), и включена админом."""
        flags = await self.flags(session)
        return {
            "translate": bool(self.translator) and flags["translate"],
            "tts": bool(self.tts) and flags["tts"],
            "ai": bool(self.ai) and flags["ai"],
            "collocations": flags["collocations"],
        }

    def configured(self) -> dict[str, bool]:
        return {"translate": bool(self.translator), "tts": bool(self.tts), "ai": bool(self.ai)}

    async def aclose(self) -> None:
        await self.http.aclose()
