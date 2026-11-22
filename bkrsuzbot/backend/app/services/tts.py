"""Озвучка китайского текста: Google Cloud Text-to-Speech (голоса cmn-CN).

Аудио кэшируется на диске (AUDIO_CACHE_DIR), чтобы не платить за повторный синтез.
MP3 — для Mini App, OGG_OPUS — для голосовых сообщений в Telegram.
"""

import base64
import hashlib
from pathlib import Path

import httpx

GOOGLE_TTS_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"
MAX_TTS_CHARS = 300


class TTSUnavailable(Exception):
    pass


class GoogleTTS:
    name = "google"

    def __init__(self, api_key: str, http: httpx.AsyncClient, voices: list[str],
                 cache_dir: str, slow_rate: float = 0.7):
        self.api_key = api_key
        self.http = http
        self.voices = voices
        self.default_voice = voices[0] if voices else "cmn-CN-Wavenet-A"
        self.cache_dir = Path(cache_dir)
        self.slow_rate = slow_rate

    def pick_voice(self, voice: str | None) -> str:
        return voice if voice in self.voices else self.default_voice

    async def synthesize(self, text: str, voice: str | None = None, slow: bool = False,
                         fmt: str = "mp3") -> bytes:
        text = text.strip()[:MAX_TTS_CHARS]
        if not text:
            raise TTSUnavailable("empty text")
        voice = self.pick_voice(voice)
        rate = self.slow_rate if slow else 1.0
        encoding = "OGG_OPUS" if fmt == "ogg" else "MP3"
        key = hashlib.sha256(f"{voice}|{rate}|{encoding}|{text}".encode()).hexdigest()
        path = self.cache_dir / key[:2] / f"{key}.{fmt}"
        if path.exists():
            return path.read_bytes()
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
        audio = base64.b64decode(r.json()["audioContent"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio)
        return audio
