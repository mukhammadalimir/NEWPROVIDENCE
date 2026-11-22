"""Заранее переводимые строки БКРС (pretranslate_bkrs): пакеты, ошибки Gemini, кэш.
Сеть не используется — httpx.MockTransport; паузы отключены."""

import json

import httpx
import pytest

from app.scripts import pretranslate_bkrs as pt
from app.services.translate import GeminiTranslator
from app.text.uzbek import typographic


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def fast(_):
        return None
    monkeypatch.setattr(pt.asyncio, "sleep", fast)


def gemini(handler):
    """handler(texts, model) -> (status, list[str] | str)."""
    calls = []

    def h(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        texts = json.loads(body["contents"][0]["parts"][0]["text"].rsplit("Input:\n", 1)[1])
        model = request.url.path.split("/models/")[1].split(":")[0]
        calls.append((model, texts))
        status, out = handler(texts, model)
        if status != 200:
            return httpx.Response(status, text="err")
        text = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})
    return httpx.AsyncClient(transport=httpx.MockTransport(h)), calls


def test_batches_respect_size_and_chars():
    texts = ["a" * 10] * 7
    assert [len(b) for b in pt.batches(texts, 3, 1000)] == [3, 3, 1]
    assert [len(b) for b in pt.batches(texts, 100, 25)] == [2, 2, 2, 1]


async def test_wrong_count_is_split_until_it_works(session):
    # модель «теряет» строку в пакетах больше 2 — пакет делится пополам
    http, calls = gemini(lambda t, m: (200, [f"uz {x}" for x in (t if len(t) <= 2 else t[:-1])]))
    run = pt.Runner("k", ["m1"], 1000, http)
    texts = [f"строка пт {i}" for i in range(5)]
    assert await run.translate(texts) == 5
    assert run.skipped == 0 and len(calls) > 1
    out = await GeminiTranslator("k", "m1", http).translate(session, texts, "ru", "uz")
    assert out == [f"uz строка пт {i}" for i in range(5)]  # всё уже в кэше


async def test_rate_limit_stops_after_retries():
    http, calls = gemini(lambda t, m: (429, ""))
    run = pt.Runner("k", ["m1"], 1000, http)
    with pytest.raises(pt.Stop, match="лимит"):
        await run.translate(["строка лимит"])
    assert len(calls) == 6


async def test_unknown_model_falls_back_and_bad_key_stops():
    http, calls = gemini(lambda t, m: (404, "") if m == "gone" else (200, [f"uz {x}" for x in t]))
    run = pt.Runner("k", ["gone", "ok"], 1000, http)
    assert await run.translate(["строка модель"]) == 1
    assert [c[0] for c in calls] == ["gone", "ok"]
    http2, _ = gemini(lambda t, m: (403, ""))
    with pytest.raises(pt.Stop, match="GEMINI_API_KEY"):
        await pt.Runner("k", ["m"], 1000, http2).translate(["строка ключ"])


async def test_overloaded_model_switches(session):
    http, calls = gemini(lambda t, m: (503, "") if m == "busy" else (200, [f"uz {x}" for x in t]))
    run = pt.Runner("k", ["busy", "free"], 1000, http)
    assert await run.translate(["строка занято"]) == 1
    assert run.tr.model == "free"


def test_uzbek_apostrophes_are_unified():
    assert typographic("e'tibor, bo'lak, g`oya") == "e’tibor, bo‘lak, g‘oya"
    assert typographic("Lu Sin 'AQ'") == "Lu Sin 'AQ'"


async def test_uz_translations_are_stored_typographic(session):
    http, _ = gemini(lambda t, m: (200, ["bo'lak, e'tibor" for _ in t]))
    (out,) = await GeminiTranslator("k", "m", http).translate(session, ["кусок пт"], "ru", "uz")
    assert out == "bo‘lak, e’tibor"


async def test_limit_on_one_model_switches_to_another():
    # у бесплатного ключа лимиты по моделям: 429 у «a» — сразу «b», без паузы
    http, calls = gemini(lambda t, m: (429, "") if m == "a" else (200, [f"uz {x}" for x in t]))
    run = pt.Runner("k", ["a", "b"], 1000, http)
    assert await run.translate(["строка лимит а"]) == 1
    assert [c[0] for c in calls] == ["a", "b"]
    http2, calls2 = gemini(lambda t, m: (429, ""))
    with pytest.raises(pt.Stop, match="у всех моделей"):
        await pt.Runner("k", ["a", "b"], 1000, http2).translate(["строка лимит все"])
    assert len(calls2) == 12  # 6 кругов по 2 модели


async def test_all_models_busy_then_recover():
    state = {"n": 0}

    def handler(t, m):
        state["n"] += 1
        return (503, "") if state["n"] <= 5 else (200, [f"uz {x}" for x in t])
    http, calls = gemini(handler)
    run = pt.Runner("k", ["a", "b"], 1000, http)
    assert await run.translate(["строка перегрузка"]) == 1
    assert len(calls) == 6 and run.busy_rounds == 0  # после успеха счётчики сброшены
