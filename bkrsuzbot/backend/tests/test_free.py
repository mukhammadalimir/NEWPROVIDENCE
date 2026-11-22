"""Бесплатный режим: озвучка edge-tts и AI-пояснения через Gemini (без платных ключей).

Сеть не используется: edge_tts подменяется заглушкой, Gemini — httpx.MockTransport.
"""

import json
import sys
import types

import httpx
import pytest

from app.config import Settings
from app.services.ai import AIUnavailable, GeminiExplainer
from app.services.container import Services
from app.services.tts import EdgeTTS, GoogleTTS, TTSUnavailable


def _settings(tmp_path, **kw) -> Settings:
    base = {"google_api_key": "", "anthropic_api_key": "", "gemini_api_key": "",
            "audio_cache_dir": str(tmp_path), "tts_provider": "auto"}
    return Settings(**{**base, **kw})


def test_auto_picks_free_providers(tmp_path):
    svc = Services(_settings(tmp_path, gemini_api_key="g"))
    assert isinstance(svc.tts, EdgeTTS)
    assert isinstance(svc.ai, GeminiExplainer)
    assert svc.configured() == {"translate": True, "tts": True, "ai": True}


def test_google_key_still_preferred(tmp_path):
    svc = Services(_settings(tmp_path, google_api_key="k"))
    assert isinstance(svc.tts, GoogleTTS) and svc.tts.voice_format == "ogg"


def test_tts_off(tmp_path):
    assert Services(_settings(tmp_path, tts_provider="off")).tts is None


@pytest.fixture
def fake_edge(monkeypatch):
    calls = []

    class Communicate:
        def __init__(self, text, voice, rate="+0%"):
            calls.append((text, voice, rate))
            self.text = text

        async def stream(self):
            yield {"type": "WordBoundary"}
            yield {"type": "audio", "data": b"MP3:"}
            yield {"type": "audio", "data": self.text.encode()}

    monkeypatch.setitem(sys.modules, "edge_tts", types.SimpleNamespace(Communicate=Communicate))
    return calls


async def test_edge_tts_synthesize_and_cache(tmp_path, fake_edge):
    tts = EdgeTTS(["zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural"], str(tmp_path), 0.7)
    audio = await tts.synthesize("你好", slow=True, fmt="mp3")
    assert audio == "MP3:你好".encode()
    assert fake_edge == [("你好", "zh-CN-XiaoxiaoNeural", "-30%")]
    # повтор — из кэша, без нового запроса
    assert await tts.synthesize("你好", slow=True) == audio
    assert len(fake_edge) == 1
    await tts.synthesize("你好", voice="zh-CN-YunxiNeural")
    assert fake_edge[-1] == ("你好", "zh-CN-YunxiNeural", "+0%")
    # неизвестный голос → голос по умолчанию
    assert tts.pick_voice("cmn-CN-Wavenet-A") == "zh-CN-XiaoxiaoNeural"


async def test_edge_tts_failure(tmp_path, monkeypatch):
    class Broken:
        def __init__(self, *a, **k):
            pass

        async def stream(self):
            raise ConnectionError("offline")
            yield  # pragma: no cover

    monkeypatch.setitem(sys.modules, "edge_tts", types.SimpleNamespace(Communicate=Broken))
    with pytest.raises(TTSUnavailable):
        await EdgeTTS([], str(tmp_path)).synthesize("鱼")


def _gemini(reply: dict | str, status: int = 200):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        if status != 200:
            return httpx.Response(status, text="err")
        text = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), seen


async def test_gemini_explainer_ok_and_cached(session):
    data = {"known": True, "usage": "Kundalik so‘z.",
            "examples": [{"zh": "我喜欢吃鱼。", "translation": "Men baliq yeyishni yaxshi ko‘raman."}]}
    http, seen = _gemini(data)
    ai = GeminiExplainer("g", "gemini-test", http)
    out = await ai.explain(session, "鱼", "yú", ["baliq"], "uz")
    assert out == data
    assert "Uzbek" in seen[0]["contents"][0]["parts"][0]["text"]
    assert seen[0]["generationConfig"]["responseMimeType"] == "application/json"
    assert await ai.explain(session, "鱼", "yú", ["baliq"], "uz") == data
    assert len(seen) == 1  # второй раз — из кэша


@pytest.mark.parametrize("reply,status", [({}, 429), ("not json", 200), ({"usage": 1}, 200)])
async def test_gemini_explainer_errors(session, reply, status):
    http, _ = _gemini(reply, status)
    with pytest.raises(AIUnavailable):
        await GeminiExplainer("g", "gemini-test", http).explain(
            session, "书", "shū", ["kitob"], "ru")
