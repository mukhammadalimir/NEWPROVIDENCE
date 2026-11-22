"""Сценарии поиска из ТЗ (п. 14)."""

from app.services.search import search


async def test_uzbek_word_baliq(session, make_services):
    r = await search(session, make_services(google_api_key=""), "baliq")
    assert r["type"] == "word" and r["source_lang"] == "uz"
    card = r["cards"][0]
    assert card["headword"] == "鱼" and card["traditional"] == "魚"
    reading = card["readings"][0]
    assert reading["pinyin"] == "yú"
    assert reading["senses"][0]["items"] == ["baliq"]
    assert reading["senses"][0]["kind"] == "curated"
    assert "条 (tiáo)" in reading["measure_word"]
    zh = [c["zh"] for c in reading["collocations"]]
    assert {"海鱼", "淡水鱼", "捕鱼"} <= set(zh)
    assert reading["examples"][0]["zh"] == "我喜欢吃鱼。"
    assert reading["examples"][0]["translation"] == "Men baliq yeyishni yaxshi ko‘raman."
    # фамилия Yú не подмешивается к значению «рыба»
    assert len(card["readings"]) == 1


async def test_uzbek_apostrophe_variants(session, make_services):
    svc = make_services(google_api_key="")
    for q in ("o‘qimoq", "o'qimoq", "ўқимоқ"):
        r = await search(session, svc, q)
        assert r["type"] == "word" and r["cards"][0]["headword"] == "学习", q


async def test_chinese_word(session, make_services):
    r = await search(session, make_services(google_api_key=""), "鱼", user_target="uz")
    assert r["type"] == "word" and r["target_lang"] == "uz"
    readings = r["cards"][0]["readings"]
    assert readings[0]["pinyin"] == "yú" and readings[0]["senses"][0]["items"] == ["baliq"]
    assert "fish" in readings[0]["english"]  # CC-CEDICT, помечено как английское
    assert readings[-1]["proper"] is True  # фамилия Yú — отдельным чтением


async def test_chinese_word_with_mt(session, make_services, google):
    r = await search(session, make_services(), "鱼", user_target="ru")
    reading = r["cards"][0]["readings"][0]
    assert reading["english_mt"] and reading["english_mt"][0] == "[ru] fish"
    assert google.calls  # перевод действительно запрошен у сервиса


async def test_pinyin_search(session, make_services):
    svc = make_services(google_api_key="")
    r = await search(session, svc, "yu")
    assert r["type"] == "choose" and r["options"] == ["pinyin", "uz"]
    for q, src in (("yu", "pinyin"), ("yu2", None), ("yú", None)):
        r = await search(session, svc, q, source=src)
        assert r["type"] == "candidates", q
        heads = [c["headword"] for c in r["candidates"]]
        assert heads[0] == "鱼", q  # слово с узбекским значением — первым
        assert "于" in heads
    r = await search(session, svc, "yu2")
    assert "语" not in [c["headword"] for c in r["candidates"]]  # yǔ — другой тон
    r = await search(session, svc, "yu")
    r = await search(session, svc, "yu", source="pinyin")
    assert "语" in [c["headword"] for c in r["candidates"]]


async def test_multiple_readings_not_mixed(session, make_services):
    r = await search(session, make_services(google_api_key=""), "行")
    readings = {x["pinyin"]: x for x in r["cards"][0]["readings"]}
    assert {"xíng", "háng"} <= set(readings)
    assert ["yurmoq", "bormoq"] in [s["items"] for s in readings["xíng"]["senses"]]
    assert ["qator", "kasb", "soha"] == readings["háng"]["senses"][0]["items"]
    hang_colloc = [c["zh"] for c in readings["háng"]["collocations"]]
    xing_colloc = [c["zh"] for c in readings["xíng"]["collocations"]]
    assert "银行" in hang_colloc and "银行" not in xing_colloc
    assert "进行" in xing_colloc and "进行" not in hang_colloc


async def test_sentence_zh_to_uz_and_ru(session, make_services):
    svc = make_services()
    r = await search(session, svc, "我喜欢吃鱼。", user_target="uz")
    assert r["type"] == "text"
    assert r["text"]["translation"] == "Men baliq yeyishni yaxshi ko‘raman."
    assert r["text"]["pinyin"].startswith("wǒ xǐhuan") or r["text"]["pinyin"].startswith("wǒ xǐhuān")
    assert [w["zh"] for w in r["text"]["words"]][:2] == ["我", "喜欢"]
    assert "mt_used" in r["notices"]
    r = await search(session, svc, "我喜欢吃鱼。", user_target="uz", target="ru")
    assert r["text"]["translation"] == "Я люблю есть рыбу."


async def test_sentence_uz_to_zh(session, make_services):
    r = await search(session, make_services(), "Men baliq yeyishni yaxshi ko'raman")
    assert r["type"] == "text" and r["source_lang"] == "uz"
    assert r["text"]["zh"] == "我喜欢吃鱼"
    assert r["text"]["pinyin"]
    assert "mt_used" in r["notices"]


async def test_uz_word_via_mt_marked(session, make_services):
    r = await search(session, make_services(), "kitob")
    # «kitob» есть в редакционном словаре → без машинного перевода
    assert r["type"] == "word" and "mt_used" not in r["notices"]


async def test_service_unavailable_messages(session, make_services, google):
    r = await search(session, make_services(google_api_key=""), "我喜欢吃鱼。")
    assert r["type"] == "text" and r["text"]["translation"] is None
    assert "translate_unavailable" in r["notices"]
    assert r["text"]["pinyin"]  # пиньинь и разбор работают без сервиса

    google.fail = True  # сервис отвечает ошибкой (фраза ещё не в кэше)
    r = await search(session, make_services(), "他是我的朋友。")
    assert "translate_failed" in r["notices"] and r["text"]["translation"] is None
    r = await search(session, make_services(), "Bugun havo juda yaxshi ekan")
    assert r["type"] == "not_found" and r["notices"] == ["translate_failed"]
