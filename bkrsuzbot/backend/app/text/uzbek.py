"""Узбекский текст: варианты апострофов (o‘, o', g‘, g') и кириллица → латиница."""

import re

# Все варианты «апострофа», которые встречаются в узбекском тексте.
_APOSTROPHES = "ʻ‘'`´’ʼ′"
_APOS_RE = re.compile(f"[{re.escape(_APOSTROPHES)}]")

_CYR_SPECIFIC = set("ўқғҳЎҚҒҲ")

_CYR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ё": "yo", "ж": "j",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "x", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "'", "ь": "", "э": "e", "ю": "yu",
    "я": "ya", "ў": "o'", "қ": "q", "ғ": "g'", "ҳ": "h",
}
_VOWELS = set("аеёиоуэюяўАЕЁИОУЭЮЯЎ")


def has_uz_cyrillic_letters(text: str) -> bool:
    return any(c in _CYR_SPECIFIC for c in text)


def cyr_to_lat(text: str) -> str:
    out = []
    for i, ch in enumerate(text):
        low = ch.lower()
        if low == "е":
            # «е» в начале слова и после гласной/ъ читается как «ye»
            prev = text[i - 1] if i else " "
            lat = "ye" if (not prev.isalpha() or prev in _VOWELS or prev in "ъЪ") else "e"
        elif low in _CYR:
            lat = _CYR[low]
        else:
            out.append(ch)
            continue
        if ch.isupper() and lat:
            lat = lat[0].upper() + lat[1:]
        out.append(lat)
    return "".join(out)


def normalize(text: str) -> str:
    """Ключ для поиска: латиница, нижний регистр, единый апостроф "'"."""
    if re.search("[а-яА-ЯёЁўқғҳЎҚҒҲ]", text):
        text = cyr_to_lat(text)
    text = _APOS_RE.sub("'", text.lower())
    return re.sub(r"\s+", " ", text).strip(" .,!?;:")


def pretty(text: str) -> str:
    """Для показа: o' → o‘, g' → g‘ (типографский вариант)."""
    return re.sub(r"([oOgG])[" + re.escape(_APOSTROPHES) + "]", r"\1‘", text)


# тутуқ белгиси: апостроф между буквами, кроме o‘/g‘ (их делает pretty); модель иногда
# пишет его как ‘ или ʻ (fe‘l → fe’l)
_TUTUQ_RE = re.compile(r"(?<=[A-Za-z])(?<![oOgG])['`´ʼ′‘ʻ](?=[A-Za-z])")


def typographic(text: str) -> str:
    """Машинный перевод на узбекский — к единому виду: o‘, g‘ и тутуқ белгиси ’
    (e'tibor → e’tibor). Модель пишет то так, то эдак."""
    return _TUTUQ_RE.sub("’", pretty(text))


def has_uz_latin_markers(text: str) -> bool:
    """o‘/g‘ или сочетания, невозможные в пиньине."""
    t = text.lower()
    return bool(re.search(r"[og][" + re.escape(_APOSTROPHES) + "]", t))
