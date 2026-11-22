"""Машинный перевод через Gemini (ответы подменяются, настоящий API не вызывается)."""

import json
from app.services.search import search
from app.services.translate import FallbackTranslator, GeminiTranslator


async def test_gemini_only(session, make_services, google):
    svc = make_services(google_api_key="", gemini_api_key="g-key")
    assert isinstance(svc.translator, GeminiTranslator)
    r = await search(session, svc, "他是老师。", user_target="uz")
    assert r["text"]["translation"] == "[gemini] 他是老师。"
    assert r["text"]["provider"] == "Google Gemini" and "mt_used" in r["notices"]
    req = google.calls[-1]
    assert req.headers["x-goog-api-key"] == "g-key" and "gemini-flash-lite-latest" in req.url.path
    assert "Uzbek (Latin script)" in req.content.decode()
    n = len(google.calls)
    await search(session, svc, "他是老师。", user_target="uz")
    assert len(google.calls) == n  # второй раз — из кэша


async def test_gemini_falls_back_to_cloud_translate(session, make_services, google):
    svc = make_services(gemini_api_key="g-key")
    assert isinstance(svc.translator, FallbackTranslator)
    google.gemini_fail = True
    r = await search(session, svc, "我喜欢吃鱼。", user_target="ru")
    assert r["text"]["translation"] == "Я люблю есть рыбу."
    assert {c.url.host for c in google.calls} >= {"generativelanguage.googleapis.com",
                                                   "translation.googleapis.com"}


async def test_gemini_bad_answer_is_failure(session, make_services, google):
    svc = make_services(google_api_key="", gemini_api_key="g-key")
    google.gemini_reply = '["a", "b"]'  # не столько строк, сколько отправлено
    r = await search(session, svc, "她喜欢喝茶。", user_target="uz")
    assert "translate_failed" in r["notices"] and r["text"]["translation"] is None


async def test_prompt_from_chinese_asks_to_translate_characters(session, make_services, google):
    svc = make_services(google_api_key="", gemini_api_key="g-key")
    await svc.translator.translate(session, ["我们明天见。"], "zh", "ru")
    prompt = json.loads(google.calls[-1].content)["contents"][0]["parts"][0]["text"]
    assert "do not leave Chinese characters" in prompt
    assert "Keep Chinese characters" not in prompt
    await svc.translator.translate(session, ["1) идти, ходить"], "ru", "uz")
    prompt = json.loads(google.calls[-1].content)["contents"][0]["parts"][0]["text"]
    assert "Keep Chinese characters" in prompt
