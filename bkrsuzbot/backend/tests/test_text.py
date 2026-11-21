from app.text import detect, pinyin, uzbek


def test_pinyin_variants_give_same_key():
    for q in ("yu2", "yú", "Yú", "YU2"):
        syls = pinyin.parse(q)
        assert pinyin.tone_key(syls) == "yu2", q
    for q in ("ni hao", "nihao", "ni3 hao3", "nǐ hǎo", "nǐhǎo", "ni3hao3"):
        assert pinyin.toneless_key(pinyin.parse(q)) == "nihao", q
    assert pinyin.tone_key(pinyin.parse("nǐ hǎo")) == "ni3hao3"
    assert pinyin.tone_key(pinyin.parse("lǜ")) == "lv4"


def test_not_pinyin():
    for q in ("baliq", "kitob", "hello", "salom"):
        assert pinyin.parse(q) is None, q


def test_pinyin_display():
    assert pinyin.numbered_to_marks("lu:4") == "lǜ"
    assert pinyin.word_marks("xue2 xi2") == "xuéxí"
    assert pinyin.word_marks("Zhong1 guo2") == "Zhōngguó"
    assert pinyin.word_marks("Xi1 an1") == "Xī'ān"


def test_detect():
    assert detect.detect("鱼").lang == "zh"
    assert detect.detect("我喜欢吃鱼。").lang == "zh"
    assert detect.detect("baliq").lang == "uz"
    assert detect.detect("yu2").lang == "pinyin"
    assert detect.detect("yú").lang == "pinyin"
    assert detect.detect("рыба").lang == "ru"
    assert detect.detect("балиқ").lang == "uz"
    # Неоднозначно — спрашиваем, а не угадываем:
    d = detect.detect("yu")
    assert d.lang is None and d.options == ["pinyin", "uz"]
    assert detect.detect("ni hao").lang is None
    assert detect.detect("салом").lang is None


def test_uzbek_apostrophes_and_cyrillic():
    variants = ["o‘qimoq", "o'qimoq", "oʻqimoq", "o`qimoq", "o’qimoq", "ўқимоқ"]
    assert {uzbek.normalize(v) for v in variants} == {"o'qimoq"}
    assert uzbek.normalize("G‘isht") == uzbek.normalize("g'isht") == "g'isht"
    assert uzbek.cyr_to_lat("Ер, сен, ҳа") == "Yer, sen, ha"
    assert uzbek.pretty("o'zbek g'isht") == "o‘zbek g‘isht"
