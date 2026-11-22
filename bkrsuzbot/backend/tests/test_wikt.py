"""Переводы ru/uz ↔ zh из Wiktionary (данные не проверены редакцией, kind="wikt")."""

import json

import pytest
from sqlalchemy import delete

from app.models import WiktPair
from app.scripts.import_wikt import run as import_wikt
from app.services.search import search


@pytest.fixture
async def wikt(tmp_path, session):
    path = tmp_path / "wikt.json"
    path.write_text(json.dumps({
        "license": "test",
        "ru": {"осень": "秋天|秋季", "небо": "天空", "рыба": "鱼|鱼肉"},
        "uz": {"kuz": "秋天|秋季", "osmon": "天空"},
    }, ensure_ascii=False), encoding="utf-8")
    assert await import_wikt(str(path)) == 8
    yield
    await session.execute(delete(WiktPair))
    await session.commit()


async def test_russian_word_from_wiktionary(session, make_services, wikt):
    r = await search(session, make_services(google_api_key=""), "осень")
    # кириллица без узбекских букв, но слово есть только в русском словаре — не спрашиваем
    assert r["type"] == "candidates" and r["source_lang"] == "ru"
    first = r["candidates"][0]
    assert first["headword"] == "秋天" and first["gloss_kind"] == "wikt" and "осень" in first["gloss"]
    assert [c["headword"] for c in r["candidates"]][:2] == ["秋天", "秋季"]


async def test_single_wiktionary_word_card(session, make_services, wikt):
    r = await search(session, make_services(google_api_key=""), "небо")
    assert r["type"] == "word"
    reading = r["cards"][0]["readings"][0]
    assert r["cards"][0]["headword"] == "天空"
    assert reading["senses"] == [{"pos": None, "items": ["небо"], "kind": "wikt", "verified": False}]


async def test_uzbek_word_from_wiktionary(session, make_services, wikt):
    r = await search(session, make_services(google_api_key=""), "kuz")
    assert r["type"] == "candidates" and r["candidates"][0]["headword"] == "秋天"


async def test_chinese_card_gets_wiktionary_meaning(session, make_services, wikt):
    r = await search(session, make_services(google_api_key=""), "秋天", target="ru")
    senses = r["cards"][0]["readings"][0]["senses"]
    assert senses[0]["kind"] == "wikt" and senses[0]["items"] == ["осень"]


async def test_curated_card_wins(session, make_services, wikt):
    # «рыба» есть в карточке редакции — сразу её карточка, без списка из Wiktionary
    r = await search(session, make_services(google_api_key=""), "рыба")
    assert r["type"] == "word" and r["cards"][0]["headword"] == "鱼"
    assert r["cards"][0]["readings"][0]["senses"][0]["kind"] == "curated"
