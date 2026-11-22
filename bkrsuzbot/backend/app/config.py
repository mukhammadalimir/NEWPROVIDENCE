"""Все настройки берутся из переменных окружения (см. .env.example)."""

from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Telegram ---
    bot_token: str = ""
    bot_username: str = ""  # без @, для кнопки «Поделиться» в Mini App
    webapp_url: str = ""  # публичный HTTPS-адрес Mini App, например https://bkrs.example.uz/
    admin_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)
    proxy_url: str = ""  # прокси для api.telegram.org (необязательно)

    # --- База данных ---
    # По умолчанию — файл SQLite рядом с ботом (бесплатно, без сервера БД).
    # Для PostgreSQL: postgresql+asyncpg://user:pass@host:5432/db
    database_url: str = "sqlite+aiosqlite:///bkrsuz.db"

    # --- Google Cloud (перевод и озвучка) ---
    google_api_key: str = ""
    google_translate_api_key: str = ""  # если пусто — используется google_api_key
    google_tts_api_key: str = ""  # если пусто — используется google_api_key
    tts_voices: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["cmn-CN-Wavenet-A", "cmn-CN-Wavenet-B",
                                 "cmn-CN-Wavenet-C", "cmn-CN-Wavenet-D"])
    tts_slow_rate: float = 0.7
    audio_cache_dir: str = "audio_cache"
    # Бесплатная озвучка (edge-tts, голоса Microsoft, без ключа) — если нет ключа Google.
    # TTS_PROVIDER: auto | google | edge | off
    tts_provider: str = "auto"
    edge_voices: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural",
                                 "zh-CN-XiaoyiNeural", "zh-CN-YunjianNeural"])

    # --- Google Gemini: бесплатный машинный перевод (ключ https://aistudio.google.com/apikey) ---
    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-lite-latest"

    # --- AI-объяснения (необязательно) ---
    anthropic_api_key: str = ""
    ai_model: str = "claude-opus-5-5"

    # --- Прочее ---
    app_env: str = "prod"  # prod | dev
    # Только для локальной разработки (APP_ENV=dev): заголовок X-Dev-User вместо initData.
    dev_auth_user_id: int = 0
    initdata_max_age: int = 24 * 3600
    rate_search_per_min: int = 30
    rate_tts_per_min: int = 30
    rate_ai_per_hour: int = 20

    @field_validator("admin_ids", "tts_voices", "edge_voices", mode="before")
    @classmethod
    def _split_list(cls, v):
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        if isinstance(v, int):
            return [v]
        return v

    @property
    def translate_key(self) -> str:
        return self.google_translate_api_key or self.google_api_key

    @property
    def tts_key(self) -> str:
        return self.google_tts_api_key or self.google_api_key

    @property
    def is_dev(self) -> bool:
        return self.app_env == "dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()
