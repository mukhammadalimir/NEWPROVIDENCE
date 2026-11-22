"""大БКРС (bkrs.info): разбор DSL, импорт, значения в карточках (ru — как в словаре,
uz — перевод тех же строк), выражения, которых нет в CC-CEDICT.

Сеть не используется: перевод ru→uz — FakeGoogle из conftest ("[uz] …")."""

import gzip
import json

import pytest
from sqlalchemy import delete

from app.bot import render
from app.db import SessionLocal
from app.models import BkrsEntry
from app.scripts.import_bkrs import parse_dsl, run
from app.services.search import search
from app.text import dsl
from test_bot_flow import buttons, harness, msg  # noqa: F401  (harness — фикстура)

# Фрагмент в формате дампа bkrs.info (заголовок, пиньинь с отступом, тело DSL).
SAMPLE = """﻿#NAME "大БКРС (test)"
#INDEX_LANGUAGE "Chinese"
#CONTENTS_LANGUAGE "Russian"

鱼
 yú
 [m1][b]I[/b] [c][i]сущ.[/i][/c][/m][m2]1) рыба; рыбный[/m][m3][*][ex]钓鱼 удить рыбу[/ex][/*][/m][m3][*][ex]飞鱼 летучая рыба[/ex][/*][/m][m3][*][ex]鱼店 рыбная лавка[/ex][/*][/m][m1][b]II [/b][p]местоим[/p][/m][m2] [i]* я,[/i] мой[/m]

行
 xíng, háng
 [m1][p]гл.[/p][/m][m2]1) [b]xíng[/b] идти, ходить[/m][m3][*][ex]行路 идти по дороге[/ex][/*][/m][m2]2) [b]xíng[/b] годиться; ладно![/m][m1][p]сущ.[/p][/m][m2]1) [b]háng[/b] ряд, строка \\[текста\\][/m][m3][*][ex]写了两行字 написать две строки[/ex][/*][/m]

一路平安
 yīlù píng'ān
 [m1]в добрый путь, счастливого пути[/m]

吃
 chī
 [m1]1) есть, кушать[/m][m1]2) [p]перен.[/p] терпеть, испытывать[/m]

不入虎穴，焉得虎子
 bù rù hǔxué, yān dé hǔzǐ
 [m1][p]посл.[/p] не войдёшь в логово тигра — не поймаешь тигрёнка[/m]

不入虎穴焉得虎子
 bùrù hǔxué yāndé hǔzǐ
 [m1][p]см.[/p] [ref]不入虎穴，焉得虎子[/ref][/m]

一打
 yīdá, yīdǎ
 [m1]1) yīdá дюжина[/m][m1]2) yīdǎ ударить, удар[/m]

是
 shì
 [m1]1) быть, являться[/m]
"""
HEADS = ["鱼", "行", "一路平安", "吃", "不入虎穴，焉得虎子", "不入虎穴焉得虎子", "一打", "是"]


@pytest.fixture(scope="module", autouse=True)
async def bkrs_data(tmp_path_factory):
    path = tmp_path_factory.mktemp("bkrs") / "dabkrs_test.gz"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(SAMPLE)
    with gzip.open(path, "rt", encoding="utf-8") as src:
        assert await run(src) == len(HEADS)
    yield
    # остальные тестовые модули ожидают базу без БКРС
    async with SessionLocal() as s:
        await s.execute(delete(BkrsEntry))
        await s.commit()


def test_parse_dsl_skips_header_and_keeps_pinyin():
    entries = list(parse_dsl(SAMPLE.splitlines(keepends=True)))
    assert [e[0] for e in entries] == HEADS
    assert entries[1][1] == "xíng, háng"
    assert entries[2][2].startswith("[m1]в добрый путь")


def test_parse_body_readings_examples_headings():
    body = list(parse_dsl(SAMPLE.splitlines()))[1][2]
    items = dsl.parse_body(body)
    # заголовок раздела относится к чтению своих строк («сущ.» — к háng, а не к xíng)
    assert [(i["kind"], i["reading"]) for i in items] == [
        ("head", "xíng"), ("sense", "xíng"), ("ex", "xíng"), ("sense", "xíng"),
        ("head", "háng"), ("sense", "háng"), ("ex", "háng")]
    sense = items[1]
    assert sense["text"] == "1) идти, ходить"  # чтение из текста убрано — оно в заголовке
    assert items[5]["text"] == "1) ряд, строка [текста]"  # \[ \] — буквальные скобки
    assert items[6]["zh"] == "写了两行字" and items[6]["tr"] == "написать две строки"
    by = dsl.assign_readings(items, ["xíng", "háng"], ["háng", "xíng"])
    assert [i["text"] for i in by["háng"] if i["kind"] == "sense"] == ["1) ряд, строка [текста]"]
    assert len([i for i in by["xíng"] if i["kind"] == "sense"]) == 2


def test_headings_are_not_meanings():
    for h in ["I", "I сущ.", "гл. А", "собств. и усл.", "Б", "I прил. /наречие",
              "II счётное слово", "I союзное наречие"]:
        assert dsl.is_heading(h), h
    for m in ["он", "рыба", "1) рыба", "II 1) рыба"]:
        assert not dsl.is_heading(m), m


async def test_ru_card_shows_bkrs_as_on_site(session, make_services):
    r = await search(session, make_services(), "鱼", user_target="ru")
    yu = next(x for x in r["cards"][0]["readings"] if x["pinyin"] == "yú")
    assert yu["bkrs_kind"] == "bkrs"
    texts = [i["text"] for i in yu["bkrs"]]
    assert "1) рыба; рыбный" in texts and "钓鱼 удить рыбу" in texts
    assert "鱼店 рыбная лавка" not in texts  # не больше 2 примеров к значению
    card = render.card_text(r["cards"][0], "ru", "ru")
    assert "大БКРС (bkrs.info)" in card and "удить рыбу" in card
    assert "CC-CEDICT" not in card.split("yú")[1].split("🔤")[0]  # английский скрыт


async def test_uz_card_translates_bkrs_lines(session, make_services, google):
    r = await search(session, make_services(), "行", user_target="uz")
    by = {x["pinyin"]: x for x in r["cards"][0]["readings"]}
    assert by["xíng"]["bkrs_kind"] == "bkrs_mt"
    assert "[uz] 1) идти, ходить" in [i["text"] for i in by["xíng"]["bkrs"]]
    ex = next(i for i in by["háng"]["bkrs"] if i["kind"] == "ex")
    assert ex["zh"] == "写了两行字" and ex["tr"] == "[uz] написать две строки"
    # переводится русский текст БКРС, а не английский CC-CEDICT
    bodies = [json.loads(c.content) for c in google.calls]
    assert any(b["source"] == "ru" and b["target"] == "uz" for b in bodies)
    assert not any(b["source"] == "en" and any("walk" in q for q in b["q"]) for b in bodies)


async def test_uz_without_translator_shows_russian(session, make_services):
    r = await search(session, make_services(google_api_key=""), "吃", user_target="uz")
    rd = r["cards"][0]["readings"][0]
    assert rd["bkrs_kind"] == "bkrs_ru"
    assert rd["bkrs"][0]["text"] == "1) есть, кушать"
    assert "ruscha ko‘rsatildi" in render.card_text(r["cards"][0], "uz", "uz")


async def test_phrase_only_in_bkrs_is_a_word_card(session, make_services):
    r = await search(session, make_services(google_api_key=""), "一路平安", user_target="ru")
    assert r["type"] == "word"
    rd = r["cards"][0]["readings"][0]
    assert rd["entry_id"] is None and rd["pinyin"] == "yīlù píng'ān"
    assert rd["approx"] and rd["bkrs"][0]["text"] == "в добрый путь, счастливого пути"


async def test_sentence_breakdown_uses_bkrs(session, make_services):
    r = await search(session, make_services(google_api_key=""), "我吃鱼。", user_target="ru")
    words = {w["zh"]: w for w in r["text"]["words"]}
    assert words["鱼"]["gloss"] == "рыба; рыбный" and words["鱼"]["gloss_kind"] == "bkrs"
    assert words["鱼"]["pinyin"] == "yú"  # обычное чтение, а не фамилия Yú
    assert words["我"]["gloss_kind"] != "bkrs"  # нет в БКРС — прежний источник


async def test_bot_card_for_bkrs_only_phrase(harness):  # noqa: F811
    dp, bot, rec = harness()
    await dp.feed_update(bot, msg(3101, "一路平安"))
    card = rec.sent()[-1]
    assert "大БКРС" in card.text and "<b>一路平安</b>" in card.text
    labels = [b.text for b in buttons(card)]
    assert any(t.startswith("⭐") for t in labels)
    assert not any(b.callback_data and b.callback_data.startswith("x:None") for b in buttons(card))


@pytest.mark.parametrize("q", ["不入虎穴，焉得虎子", "不入虎穴,焉得虎子", "不入虎穴, 焉得虎子。"])
async def test_proverb_found_with_any_comma(session, make_services, q):
    r = await search(session, make_services(google_api_key=""), q, user_target="ru")
    assert r["type"] == "word" and r["cards"][0]["headword"] == "不入虎穴，焉得虎子"
    assert "логово тигра" in r["cards"][0]["readings"][0]["bkrs"][0]["text"]


async def test_uz_keeps_human_curated_meanings_above_bkrs(session, make_services):
    r = await search(session, make_services(), "行", user_target="uz")
    text = render.card_text(r["cards"][0], "uz", "uz")
    xing = text.split("🔤 <b>xíng</b>")[1].split("🔤")[0]
    assert "yurmoq, bormoq" in xing  # редакция (человеческий узбекский)
    assert "<b>大БКРС</b>" in xing and "[uz] 1) идти, ходить" in xing  # и перевод БКРС
    ru = render.card_text((await search(session, make_services(), "行",
                                        user_target="ru"))["cards"][0], "ru", "ru")
    assert "yurmoq" not in ru and "идти, ходить" in ru  # ru — только как в БКРС


def test_neutral_tone_compound_goes_to_neutral_reading():
    from app.models import DictEntry
    from app.services.dictionary import _matches_reading
    gou = DictEntry(simplified="狗东西", pinyin_num="gou3 dong1 xi5")
    keys = ["dong1xi1", "dong1xi5"]
    assert _matches_reading(gou, "东西", "dong1xi5", keys)
    assert not _matches_reading(gou, "东西", "dong1xi1", keys)  # не «восток и запад»
    fang = DictEntry(simplified="东西方", pinyin_num="dong1 xi1 fang1")
    assert _matches_reading(fang, "东西", "dong1xi1", keys)
    assert not _matches_reading(fang, "东西", "dong1xi5", keys)
    # если нейтрального чтения у слова нет — по-прежнему подходит по слогам
    assert _matches_reading(gou, "东西", "dong1xi1", ["dong1xi1"])


async def test_see_also_entry_is_followed(session, make_services):
    r = await search(session, make_services(google_api_key=""), "不入虎穴焉得虎子", user_target="ru")
    assert "логово тигра" in r["cards"][0]["readings"][0]["bkrs"][0]["text"]


def test_inline_reading_without_markup():
    body = {h: b for h, _, b in parse_dsl(SAMPLE.splitlines())}["一打"]
    items = dsl.parse_body(body, ["yīdá", "yīdǎ"])
    assert [(i["reading"], i["text"]) for i in items] == [
        ("yīdá", "1) дюжина"), ("yīdǎ", "2) ударить, удар")]
    # в карточке нет чтения yīdǎ — строка к основному чтению, но чтение остаётся в тексте
    by = dsl.assign_readings(items, ["yīdá", "yīdǎ"], ["yīdá"])
    assert [i["text"] for i in by["yīdá"]] == ["1) дюжина", "2) yīdǎ ударить, удар"]
    # чтение с другими тонами не «совпадает» без тонов
    by2 = dsl.assign_readings(items, ["yīdá", "yīdǎ"], ["yīdá", "yīdǎ"])
    assert [i["text"] for i in by2["yīdǎ"]] == ["2) ударить, удар"]


async def test_readings_follow_bkrs_order(session, make_services):
    r = await search(session, make_services(google_api_key=""), "行", user_target="ru")
    # в CC-CEDICT порядок háng, héng, xíng; в БКРС — xíng, háng
    assert [x["pinyin"] for x in r["cards"][0]["readings"]] == ["xíng", "háng", "héng"]


def test_roman_numeral_with_reading_and_semicolon_readings():
    # как в статье 王: «wáng; wàng» и разделы «[b]I wáng[/b]»
    body = ("[m1][b]I wáng [/b] [p]сущ.[/p][/m][m2]1) ван, князь[/m]"
            "[m1][b]II wàng[/b] [p]гл.[/p][/m][m2]1) царствовать[/m]")
    assert dsl.readings_of("wáng; wàng; wǎng; yù") == ["wáng", "wàng", "wǎng", "yù"]
    items = dsl.parse_body(body, dsl.readings_of("wáng; wàng"))
    assert [(i["kind"], i["reading"], i["text"]) for i in items] == [
        ("head", "wáng", "I сущ."), ("sense", "wáng", "1) ван, князь"),
        ("head", "wàng", "II гл."), ("sense", "wàng", "1) царствовать")]


def test_neutral_collocation_only_on_main_reading():
    from app.services.dictionary import _neutral_collocations_to_main_reading
    col = lambda zh, neutral: {"zh": zh, "_neutral": neutral}  # noqa: E731
    cards = [{"readings": [
        {"pinyin": "dǎ", "proper": False, "collocations": [col("打开", False), col("拍打", True)]},
        {"pinyin": "dá", "proper": False, "collocations": [col("苏打", False), col("拍打", True)]},
    ]}]
    _neutral_collocations_to_main_reading(cards)
    assert [[c["zh"] for c in r["collocations"]] for r in cards[0]["readings"]] == [
        ["打开", "拍打"], ["苏打"]]
    assert all("_neutral" not in c for r in cards[0]["readings"] for c in r["collocations"])


async def test_bot_example_audio_uses_bkrs_example(harness):  # noqa: F811
    dp, bot, rec = harness()
    await dp.feed_update(bot, msg(3102, "鱼"))
    card = rec.sent()[-1]
    assert any(b.text.startswith("🔊 Gap") for b in buttons(card))


async def test_uz_lists_keep_curated_and_replace_english(session, make_services):
    from app.services.bkrs import apply_short_glosses

    def rows():
        return [{"zh": "是", "gloss": "to be", "gloss_kind": "cedict_en"},
                {"zh": "鱼", "gloss": "baliq", "gloss_kind": "curated"},
                {"zh": "行", "gloss": "yurmoq", "gloss_kind": "wikt"}]
    # без переводчика: английский → русский БКРС; редакция и узбекский Wiktionary остаются
    r = rows()
    await apply_short_glosses(session, make_services(google_api_key=""), r, "uz")
    assert [(x["gloss"], x["gloss_kind"]) for x in r] == [
        ("быть, являться", "bkrs"), ("baliq", "curated"), ("yurmoq", "wikt")]
    # с переводчиком: перевод БКРС, но значение редакции не трогаем
    r = rows()
    await apply_short_glosses(session, make_services(), r, "uz")
    assert [x["gloss_kind"] for x in r] == ["bkrs_mt", "curated", "bkrs_mt"]
    assert r[0]["gloss"] == "[uz] быть, являться"
    # ru — всегда как в БКРС
    r = rows()
    await apply_short_glosses(session, make_services(google_api_key=""), r, "ru")
    assert [x["gloss_kind"] for x in r] == ["bkrs", "bkrs", "bkrs"]



# ---- случаи из проверки на реальных статьях БКРС ----

def test_text_outside_blocks_and_separator():
    # 收到: «получить[m1]-----[/m]вас понял…» — раньше значением был «-----»
    items = dsl.parse_body("получить[m1]-----[/m]вас понял, информацию принял ([i]в радиообмене[/i])")
    assert [i["text"] for i in items] == ["получить", "вас понял, информацию принял (в радиообмене)"]
    from app.services.bkrs import short
    assert short(items) == "получить"


def test_roman_heading_with_unmarked_pos_is_not_the_gloss():
    from app.services.bkrs import short
    body = "[m1][b]I[/b] [c][i]прил. /наречие[/i][/c][/m][m2]1) большой, крупный[/m]"
    items = dsl.parse_body(body)
    assert [i["kind"] for i in items] == ["head", "sense"]
    assert short(items) == "большой, крупный"


def test_roman_comma_reading_markers():
    # 差: «[b]I, chà[/b] … [b]II, chā[/b]»
    body = ("[m1][b]I, chà[/b] [p]гл.[/p][/m][m2]1) не хватать[/m]"
            "[m1][b]II, chā[/b][/m][m2]1) разница[/m]")
    items = dsl.parse_body(body, ["chā", "chà"])
    assert [(i["kind"], i["reading"], i["text"]) for i in items] == [
        ("head", "chà", "I гл."), ("sense", "chà", "1) не хватать"),
        ("head", "chā", "II"), ("sense", "chā", "1) разница")]
    by = dsl.assign_readings(items, ["chā", "chà"], ["chā", "chà"])
    assert [i["text"] for i in by["chà"] if i["kind"] == "sense"] == ["1) не хватать"]


def test_sense_reading_does_not_leak_to_next_sense():
    # чтение внутри значения действует только на это значение и его примеры
    body = ("[m1][p]гл.[/p][/m][m2]1) [b]hàng[/b] ряд[/m][m3][ex]行列 ряды[/ex][/m]"
            "[m2]2) годиться[/m]")
    items = dsl.parse_body(body, ["xíng", "hàng"])
    assert [(i["kind"], i["reading"]) for i in items] == [
        ("head", "hàng"), ("sense", "hàng"), ("ex", "hàng"), ("sense", None)]


def test_reading_marker_with_separator_removed_from_text():
    items = dsl.parse_body("[m1]1) [b]nà[/b], (также 那一) указательное: тот[/m]", ["nà", "nǎ"])
    assert items[0]["text"] == "1) (также 那一) указательное: тот" and items[0]["reading"] == "nà"


def test_proverb_pinyin_is_one_reading():
    assert dsl.readings_of("bù rù hǔxué, yān dé hǔzǐ", "不入虎穴，焉得虎子") == [
        "bù rù hǔxué, yān dé hǔzǐ"]
    assert dsl.readings_of("dǎ, dá", "打") == ["dǎ", "dá"]


def test_split_example_digits_and_punctuation():
    assert dsl.split_example("东西约600米 с востока") == ("东西约600米", "с востока")
    assert dsl.split_example("是不是有点意思? Интересно, не так ли?") == (
        "是不是有点意思?", "Интересно, не так ли?")
    assert dsl.split_example("打电话 позвонить") == ("打电话", "позвонить")
    assert dsl.split_example("SMS 短信 2G сеть") == ("SMS 短信", "2G сеть")
    assert dsl.split_example("только русский текст") == ("", "только русский текст")


def test_tags_with_attributes_are_removed():
    items = dsl.parse_body("[m1][c brown]разг.[/c] [c green]книжн.[/c] врач[/m]")
    assert items[0]["text"] == "разг. книжн. врач"


def test_surname_reading_does_not_take_the_article():
    assert dsl.match_reading("wáng", ["Wáng", "wáng"]) == "wáng"
    assert dsl.match_reading("Wáng", ["Wáng", "wáng"]) == "Wáng"
    by = dsl.assign_readings(dsl.parse_body("[m1]1) князь[/m]"), ["wáng"], ["Wáng", "wáng"])
    assert list(by) == ["wáng"]


def test_export_puts_proper_readings_last():
    from app.models import DictEntry
    from app.scripts.export_offline import reading_key
    rows = [DictEntry(id=1, source="cedict", simplified="王", pinyin_num="Wang2"),
            DictEntry(id=2, source="cedict", simplified="王", pinyin_num="wang2")]
    ordered = sorted(rows, key=lambda e: (e.source != "curated",
                                          e.pinyin_num[:1] != e.pinyin_num[:1].lower(), e.id))
    assert [reading_key(e.pinyin_num) for e in ordered] == ["wang2|false", "wang2|true"]


async def test_short_gloss_of_the_shown_reading(session):
    from app.services.bkrs import find, short_for
    e = (await find(session, ["行"]))["行"]
    assert short_for(e, "háng").startswith("ряд, строка")
    assert short_for(e, "xíng").startswith("идти, ходить")
    assert short_for(e, "hèng") == ""  # такого чтения в статье нет — не подменяем
    assert short_for(e).startswith("идти, ходить")
