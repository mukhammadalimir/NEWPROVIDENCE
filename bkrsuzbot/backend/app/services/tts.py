"""Озвучка китайского текста.

- GoogleTTS — Google Cloud Text-to-Speech (голоса cmn-CN, платно сверх квоты).
- EdgeTTS — бесплатно, без ключа: голоса Microsoft Edge (zh-CN-*Neural) через пакет edge-tts.

Аудио кэшируется на диске (AUDIO_CACHE_DIR), чтобы не синтезировать повторно.
MP3 — для Mini App; для голосовых в Telegram — OGG_OPUS (Google) или MP3 (Edge).
"""

import base64
import hashlib
from pathlib import Path

import httpx

GOOGLE_TTS_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"
MAX_TTS_CHARS = 300


class TTSUnavailable(Exception):
    pass


class _CachedTTS:
    name = ""
    voice_format = "mp3"  # формат голосового сообщения в Telegram

    def __init__(self, voices: list[str], cache_dir: str, slow_rate: float, fallback_voice: str):
        self.voices = voices
        self.default_voice = voices[0] if voices else fallback_voice
        self.cache_dir = Path(cache_dir)
        self.slow_rate = slow_rate

    def pick_voice(self, voice: str | None) -> str:
        return voice if voice in self.voices else self.default_voice

    def _cache_id(self, text: str, voice: str, rate: float, fmt: str) -> str:
        return f"{self.name}|{voice}|{rate}|{fmt}|{text}"

    async def _call(self, text: str, voice: str, rate: float, fmt: str) -> bytes:
        raise NotImplementedError

    async def synthesize(self, text: str, voice: str | None = None, slow: bool = False,
                         fmt: str = "mp3") -> bytes:
        text = text.strip()[:MAX_TTS_CHARS]
        if not text:
            raise TTSUnavailable("empty text")
        voice = self.pick_voice(voice)
        rate = self.slow_rate if slow else 1.0
        key = hashlib.sha256(self._cache_id(text, voice, rate, fmt).encode()).hexdigest()
        path = self.cache_dir / key[:2] / f"{key}.{fmt}"
        if path.exists():
            return path.read_bytes()
        audio = await self._call(text, voice, rate, fmt)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio)
        return audio


class GoogleTTS(_CachedTTS):
    name = "google"
    voice_format = "ogg"

    def __init__(self, api_key: str, http: httpx.AsyncClient, voices: list[str],
                 cache_dir: str, slow_rate: float = 0.7):
        super().__init__(voices, cache_dir, slow_rate, "cmn-CN-Wavenet-A")
        self.api_key = api_key
        self.http = http

    def _cache_id(self, text: str, voice: str, rate: float, fmt: str) -> str:
        # прежний формат ключа — уже оплаченный кэш остаётся в силе
        return f"{voice}|{rate}|{'OGG_OPUS' if fmt == 'ogg' else 'MP3'}|{text}"

    async def _call(self, text: str, voice: str, rate: float, fmt: str) -> bytes:
        encoding = "OGG_OPUS" if fmt == "ogg" else "MP3"
        try:
            r = await self.http.post(
                GOOGLE_TTS_URL,
                params={"key": self.api_key},
                json={
                    "input": {"text": text},
                    "voice": {"languageCode": "cmn-CN", "name": voice},
                    "audioConfig": {"audioEncoding": encoding, "speakingRate": rate},
                },
                timeout=20,
            )
        except httpx.HTTPError as e:
            raise TTSUnavailable(f"network: {e.__class__.__name__}") from e
        if r.status_code != 200:
            raise TTSUnavailable(f"http {r.status_code}: {r.text[:200]}")
        return base64.b64decode(r.json()["audioContent"])


class EdgeTTS(_CachedTTS):
    """Бесплатная озвучка голосами Microsoft Edge (пакет edge-tts, ключ не нужен).

    Сервис неофициальный: может измениться без предупреждения — тогда кнопка
    озвучки сообщит об ошибке, а остальной бот продолжит работать."""

    name = "edge"
    voice_format = "mp3"

    def __init__(self, voices: list[str], cache_dir: str, slow_rate: float = 0.7):
        super().__init__(voices, cache_dir, slow_rate, "zh-CN-XiaoxiaoNeural")

    async def _call(self, text: str, voice: str, rate: float, fmt: str) -> bytes:
        try:
            import edge_tts
        except ImportError as e:
            raise TTSUnavailable("edge-tts is not installed") from e
        pct = round((rate - 1.0) * 100)
        try:
            comm = edge_tts.Communicate(text, voice, rate=f"{pct:+d}%")
            audio = b"".join([c["data"] async for c in comm.stream() if c["type"] == "audio"])
        except Exception as e:  # сеть, изменения сервиса и т.п.
            raise TTSUnavailable(f"edge: {e.__class__.__name__}: {str(e)[:150]}") from e
        if not audio:
            raise TTSUnavailable("edge: empty audio")
        return audio
