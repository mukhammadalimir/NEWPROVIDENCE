"""Определение языка ввода. При неоднозначности — не угадываем, а спрашиваем."""

import re
from dataclasses import dataclass, field

from app.text import pinyin, uzbek

HAN_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿\U00020000-\U0002ffff]")
CYR_RE = re.compile(r"[а-яёА-ЯЁўқғҳЎҚҒҲ]")
LAT_RE = re.compile(r"[a-zA-Zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜü]")
TONE_MARK_RE = re.compile(r"[āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ]", re.I)
RU_ONLY = set("ыщЫЩ")

# Языки ввода
ZH, PINYIN, UZ, RU = "zh", "pinyin", "uz", "ru"
SOURCES = (ZH, PINYIN, UZ, RU)


@dataclass
class Detection:
    lang: str | None  # None — неоднозначно, нужно спросить пользователя
    options: list[str] = field(default_factory=list)  # варианты для выбора
    alternatives: list[str] = field(default_factory=list)  # «искать иначе» после ответа


def detect(text: str) -> Detection:
    t = text.strip()
    han = len(HAN_RE.findall(t))
    cyr = len(CYR_RE.findall(t))
    lat = len(LAT_RE.findall(t))
    if han and han >= (cyr + lat) / 3:
        return Detection(ZH)
    if cyr > lat:
        if uzbek.has_uz_cyrillic_letters(t):
            return Detection(UZ, alternatives=[RU])
        if any(c in RU_ONLY for c in t):
            return Detection(RU, alternatives=[UZ])
        # Кириллица без явных признаков: может быть и русским, и узбекским.
        return Detection(None, options=[RU, UZ])
    if lat:
        if uzbek.has_uz_latin_markers(t):
            return Detection(UZ)
        syls = pinyin.parse(t)
        if syls is None:
            return Detection(UZ)
        if TONE_MARK_RE.search(t) or re.search(r"[a-z][1-5]\b|[a-z][1-5][a-z]", t.lower()):
            return Detection(PINYIN)
        # "yu", "ni hao", "men": это может быть и пиньинь, и узбекское слово.
        return Detection(None, options=[PINYIN, UZ])
    return Detection(None, options=[ZH, UZ, RU])
