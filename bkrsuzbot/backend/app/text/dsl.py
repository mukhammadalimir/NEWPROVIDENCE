"""Разбор статей 大БКРС в разметке DSL (Lingvo / GoldenDict).

Тело статьи — одна строка из блоков [m1]…[/m] … [m4]…[/m] (уровень отступа).
Внутри: [ex]пример[/ex], [p]помета[/p] (гл., сущ., юр.), [i]/[c] — комментарии,
[b]…[/b] — римская цифра раздела или чтение (dǎ / xíng), [ref]…[/ref] — ссылка,
[*]…[/*] — второстепенное, \\[ \\] — буквальные скобки.

Результат — список строк статьи с уровнем, видом (head | sense | ex) и чтением,
к которому строка относится (если в статье несколько чтений и они размечены).
"""

import re
import unicodedata

M_RE = re.compile(r"\[m(\d)\](.*?)\[/m\]", re.S)
B_RE = re.compile(r"\[b\]\s*(.*?)\s*\[/b\]", re.S)
TAG_RE = re.compile(r"\[/?(?:m\d?|i|c|p|b|ex|ref|\*|com|trn|lang[^\]]*|sup|sub|u|s|t)\]")
CYR_RE = re.compile(r"[А-Яа-яЁё]")
ROMAN_RE = re.compile(r"^[IVXL]+\.?$")
# Чтение: латиница с тонами, без кириллицы; может быть из нескольких слогов.
PINYIN_RE = re.compile(r"^[a-zA-ZüÜÀ-ɏ̀-ͯ'’\- ]+$")
NUM_PREFIX_RE = re.compile(r"^(?:\d+\)|[а-я]\))\s*")
HAN_RE = re.compile(r"[㐀-鿿豈-﫿]")

_ESC_L, _ESC_R = "\x01", "\x02"


def _unescape(s: str) -> str:
    return s.replace(_ESC_L, "[").replace(_ESC_R, "]")


def _clean(s: str) -> str:
    s = TAG_RE.sub("", s)
    s = _unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\(\s+", "(", s)
    return re.sub(r"\s+([,;.)])", r"\1", s)


def norm_pinyin(s: str) -> str:
    """Сравнение чтений: нижний регистр, без пробелов/апострофов/дефисов."""
    s = unicodedata.normalize("NFC", s.lower())
    return re.sub(r"[\s'’\-·]", "", s).replace("u:", "ü").replace("v", "ü")


def strip_tones(s: str) -> str:
    s = unicodedata.normalize("NFD", norm_pinyin(s))
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn").replace("ü", "u")


def is_reading(s: str) -> bool:
    s = s.strip()
    return (bool(s) and not ROMAN_RE.match(s) and bool(PINYIN_RE.match(s))
            and any(ch.lower() in "aeiouüāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ" for ch in s)
            and not CYR_RE.search(s))


def readings_of(pinyin_line: str) -> list[str]:
    """«dǎ, dá» → ["dǎ", "dá"]; «wáng; wàng; wǎng; yù» → [...] (в БКРС бывают оба разделителя)."""
    return [p.strip() for p in re.split(r"[,;]", pinyin_line) if p.strip()]


ROMAN_READING_RE = re.compile(r"^([IVXL]+)\.?\s+(.+)$")


def reading_in_b(content: str) -> tuple[str | None, str | None]:
    """Содержимое [b]…[/b] → (римская цифра раздела, чтение).
    «dǎ» → (None, "dǎ"); «I wáng» → ("I", "wáng"); «II» → (None, None)."""
    c = _clean(content)
    m = ROMAN_READING_RE.match(c)
    if m and is_reading(m.group(2)):
        return m.group(1), m.group(2)
    if not m and is_reading(c):
        return None, c
    return None, None


def split_example(text: str) -> tuple[str, str]:
    """«不许打人 нельзя прибегать к побоям» → ("不许打人", "нельзя прибегать к побоям")."""
    m = CYR_RE.search(text)
    if not m:
        return text.strip(), ""
    cut = m.start()
    # если перед кириллицей стоит открывающая скобка/кавычка — переносим её в перевод
    while cut > 0 and text[cut - 1] in "([«\"":
        cut -= 1
    zh, ru = text[:cut].strip(), text[cut:].strip()
    if not HAN_RE.search(zh):  # пример без иероглифов — это обычный текст
        return "", text.strip()
    return zh, ru


# «I», «сущ.», «гл. А», «собств. и усл.» — заголовок раздела, а не значение.
HEAD_RE = re.compile(r"(?:[IVXL]+\.?\s*)?(?:[А-Я]\.?\s*)?(?:[а-яё]{1,8}\.\s*(?:и\s+)?)*(?:[А-Я]\.?)?")


def is_heading(rest: str) -> bool:
    return not rest or bool(HEAD_RE.fullmatch(rest.strip()))


def parse_body(body: str, readings: list[str] | None = None) -> list[dict]:
    """Строки статьи: {"level", "kind", "reading", "text"} (+ "zh"/"tr" для примеров).

    text — русский текст без разметки; чтение, совпадающее с заголовком раздела,
    из текста убирается (карточка и так показывает его). readings — чтения статьи из
    строки пиньиня: в БКРС чтение иногда написано прямо в тексте без [b] («1) yīdá дюжина»)."""
    known = {norm_pinyin(r): r for r in (readings or []) if len(readings or []) > 1}
    body = body.replace("\\[", _ESC_L).replace("\\]", _ESC_R)
    blocks = M_RE.findall(body) or [("1", body)]
    items: list[dict] = []
    current: str | None = None
    for level_s, inner in blocks:
        level = int(level_s)
        is_ex = "[ex]" in inner
        reading_here = None
        for b in B_RE.findall(inner):
            _, rd = reading_in_b(b)
            if rd:
                reading_here = rd
        if reading_here and not is_ex:
            current = reading_here

            def drop_reading(m: re.Match) -> str:
                roman, rd = reading_in_b(m.group(1))
                if rd != reading_here:
                    return m.group(0)
                return f"[b]{roman}[/b]" if roman else ""  # «I wáng» → раздел «I»

            inner = B_RE.sub(drop_reading, inner)
        text = _clean(inner)
        if not text:
            continue
        if known and not is_ex and not reading_here:
            m = re.match(r"^((?:\d+\)|[а-я]\))\s*)(\S+)\s+(.*)$", text)
            if m and norm_pinyin(m.group(2)) in known:
                current = known[norm_pinyin(m.group(2))]
                text = m.group(1) + m.group(3)
        if is_ex:
            zh, tr = split_example(text)
            items.append({"level": level, "kind": "ex", "reading": current, "text": text,
                          "zh": zh, "tr": tr})
            continue
        # заголовок раздела: только римская цифра / буква / помета части речи, без значения
        rest = _clean(re.sub(r"\[p\].*?\[/p\]", "", B_RE.sub("", inner)))
        kind = "head" if is_heading(rest) else "sense"
        items.append({"level": level, "kind": kind, "reading": current, "text": text})
    return items


def _with_reading(text: str, reading: str) -> str:
    m = NUM_PREFIX_RE.match(text)
    return f"{m.group(0)}{reading} {text[m.end():]}" if m else f"{reading} {text}"


def assign_readings(items: list[dict], entry_readings: list[str],
                    card_readings: list[str]) -> dict[str, list[dict]]:
    """Распределяет строки статьи по чтениям карточки (ключ — чтение карточки как в
    card_readings). Строки без размеченного чтения:
    - если в статье одно чтение — к нему;
    - иначе — к первому чтению карточки, совпавшему с одним из чтений статьи."""
    def match(r: str | None) -> str | None:
        if not r:
            return None
        n = norm_pinyin(r)
        for c in card_readings:
            if norm_pinyin(c) == n:
                return c
        if strip_tones(r) != n:  # у чтения есть тоны и оно другое (yīdǎ ≠ yīdá)
            return None
        bare = [c for c in card_readings if strip_tones(c) == strip_tones(r)]
        return bare[0] if len(bare) == 1 else None

    default = None
    for r in entry_readings:
        default = match(r)
        if default:
            break
    if default is None and card_readings:
        default = card_readings[0]

    out: dict[str, list[dict]] = {}
    marked = any(it["reading"] for it in items)
    for it in items:
        target = match(it["reading"]) if marked and it["reading"] else None
        if marked and it["reading"] and target is None:
            # чтения нет в карточке — строка идёт к основному чтению, а само чтение
            # остаётся в тексте, как на сайте («2) yīdǎ ударить»)
            target = default
            if it["kind"] == "sense":
                it = {**it, "text": _with_reading(it["text"], it["reading"])}
        out.setdefault(target or default, []).append(it)
    out.pop(None, None)
    return out
