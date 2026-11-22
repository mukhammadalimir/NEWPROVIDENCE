"""Тесты работают с настоящей PostgreSQL (TEST_DATABASE_URL) или с файлом SQLite
(TEST_DATABASE_URL=sqlite+aiosqlite:///test.db) и фрагментом CC-CEDICT.

Внешние сервисы (Google, Telegram) не вызываются: вместо сети используется
httpx.MockTransport — это тестовые двойники, а не рабочая интеграция.
"""

import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from urllib.parse import urlencode

os.environ["DATABASE_URL"] = os.getenv(
    "TEST_DATABASE_URL", "postgresql+asyncpg://bkrsuz:bkrsuz@localhost:5432/bkrsuz_test")
os.environ["BOT_TOKEN"] = "123456:TEST-TOKEN"
os.environ["ADMIN_IDS"] = "1000"
os.environ["APP_ENV"] = "prod"

import httpx  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import insert, text  # noqa: E402

from app.config import Settings, get_settings  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.models import DictEntry  # noqa: E402
from app.scripts.import_cedict import load_freq, measure_word, parse_u8  # noqa: E402
from app.services.container import Services  # noqa: E402
from app.text.pinyin import keys_from_numbered  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = Path(__file__).parent / "data" / "cedict_sample.u8"


@pytest.fixture(scope="session", autouse=True)
def database():
    """Чистая схема через миграции Alembic + данные."""
    import asyncio

    async def reset():
        if engine.dialect.name == "sqlite":
            await engine.dispose()
            db_file = Path(engine.url.database)
            for f in (db_file, Path(f"{db_file}-wal"), Path(f"{db_file}-shm")):
                f.unlink(missing_ok=True)
            return
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
        await engine.dispose()

    asyncio.run(reset())
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    command.upgrade(cfg, "head")

    async def load():
        freq = load_freq()
        async with SessionLocal() as s:
            rows = []
            for trad, simp, pin, defs in parse_u8(SAMPLE.read_text("utf-8")):
                defs, cl = measure_word([d for d in defs if d])
                tk, k = keys_from_numbered(pin)
                rows.append(dict(source="cedict", simplified=simp, traditional=trad,
                                 pinyin_num=pin, pinyin_tone_key=tk, pinyin_key=k,
                                 senses=[{"en": defs}], measure_word=cl, usage={},
                                 collocations=[], examples=[], verified=False,
                                 freq=freq.get(simp, 0)))
            await s.execute(insert(DictEntry), rows)
            await s.commit()
        from app.scripts import seed
        await seed.main()
        await engine.dispose()

    asyncio.run(load())
    yield


class FakeGoogle:
    """Имитация ответов Google Translation и TTS по их формату (для тестов)."""

    TRANSLATIONS = {
        ("uz", "zh-CN", "Men baliq yeyishni yaxshi ko'raman"): "我喜欢吃鱼",
        ("zh-CN", "uz", "我喜欢吃鱼。"): "Men baliq yeyishni yaxshi ko‘raman.",
        ("zh-CN", "ru", "我喜欢吃鱼。"): "Я люблю есть рыбу.",
        ("uz", "zh-CN", "kitob"): "书",
    }

    def __init__(self):
        self.calls = []
        self.fail = False
        self.gemini_fail = False
        self.gemini_reply = None  # подмена текста ответа Gemini (для проверки ошибок)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.fail:
            return httpx.Response(503, text="unavailable")
        body = json.loads(request.content)
        if request.url.host == "translation.googleapis.com":
            out = [{"translatedText": self.TRANSLATIONS.get(
                (body["source"], body["target"], q), f"[{body['target']}] {q}")}
                for q in body["q"]]
            return httpx.Response(200, json={"data": {"translations": out}})
        if request.url.host == "generativelanguage.googleapis.com":
            if self.gemini_fail:
                return httpx.Response(429, text="quota")
            prompt = body["contents"][0]["parts"][0]["text"]
            texts = json.loads(prompt.rsplit("Input:\n", 1)[1])
            out = self.gemini_reply or json.dumps([f"[gemini] {t}" for t in texts], ensure_ascii=False)
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": out}]}}]})
        if request.url.host == "texttospeech.googleapis.com":
            fake = f"AUDIO:{body['input']['text']}:{body['audioConfig']['speakingRate']}"
            return httpx.Response(200, json={"audioContent": base64.b64encode(fake.encode()).decode()})
        return httpx.Response(404)


@pytest.fixture
def google():
    return FakeGoogle()


@pytest.fixture
def make_services(tmp_path, google):
    def make(**overrides) -> Services:
        settings = Settings(**{"google_api_key": "test-key", "audio_cache_dir": str(tmp_path),
                               "anthropic_api_key": "", "gemini_api_key": "",
                               "gemini_model": "gemini-flash-lite-latest",
                               # без ключа Google — без озвучки (бесплатный edge-tts проверяется отдельно)
                               "tts_provider": "google", **overrides})
        return Services(settings, http=httpx.AsyncClient(transport=httpx.MockTransport(google.handler)))
    return make


@pytest.fixture
async def session():
    async with SessionLocal() as s:
        yield s


def sign_init_data(user_id: int, token: str = "123456:TEST-TOKEN", auth_date: int | None = None,
                   first_name: str = "Test") -> str:
    """Подпись initData так же, как это делает Telegram (для тестов)."""
    fields = {
        "auth_date": str(auth_date or int(time.time())),
        "query_id": "AAH-test",
        "user": json.dumps({"id": user_id, "first_name": first_name, "language_code": "uz"},
                           separators=(",", ":")),
    }
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


@pytest.fixture
async def api(make_services):
    from app.api.main import app
    get_settings.cache_clear()
    app.state.services = make_services()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    await engine.dispose()


def auth(user_id: int) -> dict:
    return {"Authorization": f"tma {sign_init_data(user_id)}"}
