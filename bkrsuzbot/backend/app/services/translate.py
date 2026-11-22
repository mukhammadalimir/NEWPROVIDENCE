"""Машинный перевод: Google Gemini (бесплатный ключ AI Studio) и/или
Google Cloud Translation API (v2, ключ API).

Поддерживает узбекский (uz, латиница), русский (ru), китайский (zh-CN) и английский (en).
Результаты кэшируются в таблице cache_items (отдельно для каждого провайдера).
Если заданы оба ключа — сначала Gemini, при ошибке — Cloud Translation.
"""

import hashlib
import json
import logging
import re
from collections import Counter

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CacheItem
from app.services.events import log_event
from app.text import uzbek

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
                        tgt: str, partial: bool = False) -> list[str | None]:
        """Переводит список строк; повторные запросы берутся из кэша.

        partial=True: если сервис не ответил, вернуть то, что есть в кэше (None — перевода
        нет), а не исключение. Для ru→uz (строки БКРС) перевод проверяется (uz_problem):
        негодный переспрашивается по одной строке, а если и так негоден — не кэшируется
        (в partial — None, иначе возвращается как есть)."""
        if not texts:
            return []
        keys = [_key(self.name, src, tgt, t) for t in texts]
        cached = {
            c.key: c.value["text"]
            for c in (await session.scalars(
                select(CacheItem).where(CacheItem.key.in_(set(keys))))).all()
        }
        rejected: dict[str, str] = {}
        missing = [(k, t) for k, t in zip(keys, texts) if k not in cached]
        if missing:
            uniq = dict(missing)
            try:
                result = await self._call(list(uniq.values()), src, tgt)
            except TranslationUnavailable as e:
                await log_event(session, "translate", False, f"{self.name}: {e}")
                # сразу фиксируем: иначе в SQLite блокировка записи держится, пока
                # FallbackTranslator ждёт ответа следующего провайдера по сети
                await session.commit()
                if not partial:
                    raise
                return [cached.get(k) for k in keys]
            check = src == "ru" and tgt == "uz"
            bad: list[tuple[str, str]] = []
            for (k, t), value in zip(uniq.items(), result):
                value = uzbek.typographic(fix_uz_numbering(value)) if tgt == "uz" else value
                if check and uz_problem(t, value):
                    bad.append((k, t))
                    rejected[k] = value
                    continue
                cached[k] = value
                await session.merge(CacheItem(key=k, kind="mt", value={"text": value}))
            if bad and len(uniq) > 1:  # в большом пакете модель сбилась — по одной строке
                for k, t in bad:
                    try:
                        (value,) = await self._call([t], src, tgt)
                    except TranslationUnavailable:
                        continue
                    value = uzbek.typographic(fix_uz_numbering(value))
                    if not uz_problem(t, value):
                        rejected.pop(k, None)
                        cached[k] = value
                        await session.merge(CacheItem(key=k, kind="mt", value={"text": value}))
            await log_event(session, "translate", True, f"{self.name} {src}->{tgt} x{len(uniq)}"
                            + (f", rejected {len(rejected)}" if rejected else ""))
            await session.commit()
        if partial:
            return [cached.get(k) for k in keys]
        return [cached.get(k, rejected.get(k)) for k in keys]


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
{keep_rule}
- A dictionary gloss or a single word/set phrase → a short dictionary meaning; a full sentence →
  a natural, accurate sentence.
- Do not add explanations, do not omit or invent meanings. Use the commonly accepted term.

Input:
{texts}"""


KEEP_OTHER = ("- Keep Chinese characters, pinyin, numbers, numbering like 1) 2) and "
              "separators (; / ,) unchanged; write letter numbering а) б) в) as a) b) v).")
# Русские пометы БКРС — единообразно (раньше каждая партия сокращала по-своему)
KEEP_FROM_RU = KEEP_OTHER + (
    "\n- Dictionary labels — translate always the same way: см. → qarang; вм. → o‘rniga; "
    "сокр. → qisq.; разг. → so‘zl.; уст./устар./стар. → esk.; книжн. → kitobiy; "
    "перен. → ko‘chma; вежл. → hurm.; бран. → so‘k.; диал. → shev.; посл. → maqol; "
    "гл. (part of speech) → fe’l; сущ. → ot; прил. → sifat; нареч. → ravish; "
    "мест./местоим. → olmosh; числ. → son; частица → yuklama; союз → bog‘lovchi; "
    "предлог → predlog; послелог → ko‘makchi; междометие → undov; счётное слово → hisob so‘z; "
    "собств. → atoqli; г. (city) → sh.; юр. → huq.; мед. → tib.; будд. → budd.")
# Перевод С китайского: иероглифы как раз и надо перевести (раньше правило «сохранять
# иероглифы» противоречило задаче и давало непереведённые фразы).
KEEP_FROM_ZH = ("- Translate the Chinese text fully; do not leave Chinese characters in the "
                "result (only transliterate proper names). Keep numbers unchanged.")


class GeminiTranslator(CachedTranslator):
    """Перевод через Gemini API (ключ AI Studio: https://aistudio.google.com/apikey)."""

    name = "gemini"
    label = "Google Gemini"

    def __init__(self, api_key: str, model: str, http: httpx.AsyncClient, timeout: float = 20):
        super().__init__(http)
        self.api_key = api_key
        self.model = model
        self.timeout = timeout  # для больших пакетов (pretranslate_bkrs) — больше

    async def _call(self, texts: list[str], src: str, tgt: str) -> list[str]:
        keep = {"zh": KEEP_FROM_ZH, "ru": KEEP_FROM_RU}.get(src, KEEP_OTHER)
        prompt = GEMINI_PROMPT.format(src=LANG_NAMES[src], tgt=LANG_NAMES[tgt], keep_rule=keep,
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
                                     headers={"x-goog-api-key": self.api_key}, timeout=self.timeout)
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
                        tgt: str, partial: bool = False) -> list[str | None]:
        err: TranslationUnavailable | None = None
        best: list[str | None] | None = None
        for p in self.providers:
            try:
                out = await p.translate(session, texts, src, tgt, partial=partial)
            except TranslationUnavailable as e:
                err = e
                continue
            if not partial or all(v is not None for v in out):
                return out
            # partial: недостающее пробуем у следующего провайдера
            best = out if best is None else [a if a is not None else b for a, b in zip(best, out)]
        if best is not None:
            return best
        raise err or TranslationUnavailable("no providers")


_CYR = re.compile(r"[А-Яа-яЁёЎўҚқҒғҲҳ]")
_HAN = re.compile(r"[㐀-鿿豈-﫿\U00020000-\U0003ffff]")
# письменности и буквы, которых нет в узбекской латинице (Hangul, арабица, греческий,
# турецкие/азербайджанские ş ç ğ ı ə и т.п.)
_FOREIGN = re.compile(r"[가-힯ᄀ-ᇿ؀-ۿͰ-ϿşçğıəŞÇĞİƏšžñ]")
_LEAD_NUM = re.compile(r"^\s*((?:[IVXL]+\s+)?\d+\))")
_CYR_LETTER_NUM = re.compile(r"(?<![\w‘’])([абвгдежзик])\)")
_CYR_TO_LAT = dict(zip("абвгдежзик", ["a", "b", "v", "g", "d", "e", "j", "z", "i", "k"]))


def fix_uz_numbering(text: str) -> str:
    """Буквенная нумерация БКРС «а) б)» в узбекском — латиницей «a) b)»."""
    return _CYR_LETTER_NUM.sub(lambda m: _CYR_TO_LAT[m.group(1)] + ")", text)


def uz_problem(src: str, out: str) -> str | None:
    """Почему машинный перевод строки БКРС ru→uz негоден (None — годен): осталась
    кириллица, чужие буквы, потеряны/заменены иероглифы, нумерация или числа."""
    if not out or not out.strip():
        return "empty"
    if _CYR.search(out):
        return "cyrillic"
    foreign = {ch for ch in _FOREIGN.findall(out) if ch not in src}
    if foreign:
        return "foreign letters " + "".join(sorted(foreign))
    if Counter(_HAN.findall(src)) != Counter(_HAN.findall(out)):
        return "chinese characters changed"
    m = _LEAD_NUM.match(src)
    if m and not out.lstrip().startswith(m.group(1)):
        return "numbering lost"
    if Counter(re.findall(r"\d+", src)) != Counter(re.findall(r"\d+", out)):
        return "numbers changed"
    return None


def _key(provider: str, src: str, tgt: str, text: str) -> str:
    return hashlib.sha256(f"mt|{provider}|{src}|{tgt}|{text}".encode()).hexdigest()
