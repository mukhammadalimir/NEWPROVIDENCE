"""Разбор статей 大БКРС в разметке DSL (Lingvo / GoldenDict).

Тело статьи — строка из блоков [m1]…[/m] … [m4]…[/m] (уровень отступа); текст бывает
и вне блоков («получить[m1]-----[/m]вас понял…»), «-----» — разделитель, не значение.
Внутри: [ex]пример[/ex], [p]помета[/p] (гл., сущ., юр.), [i]/[c] (и [c brown]) —
комментарии, [b]…[/b] — римская цифра раздела и/или чтение («dǎ», «I wáng», «I, chà»),
[ref]…[/ref] — ссылка, [*]…[/*] — второстепенное, \\[ \\] — буквальные скобки.

Результат — список строк статьи с уровнем, видом (head | sense | ex) и чтением, к которому
строка относится. Чтение в заголовке раздела действует до следующего заголовка; чтение
внутри значения («2) [b]xíng[/b] …») — только для этого значения и его примеров.
"""

import re
import unicodedata

M_RE = re.compile(r"\[m(\d)\](.*?)\[/m\]", re.S)
B_RE = re.compile(r"\[b\]\s*(.*?)\s*\[/b\]", re.S)
TAG_RE = re.compile(r"\[/?(?:m\d?|i|c|p|b|ex|ref|\*|com|trn|lang|sup|sub|u|s|t)(?:\s[^\]]*)?\]")
CYR_RE = re.compile(r"[А-Яа-яЁё]")
ROMAN_RE = re.compile(r"^[IVXL]+\.?$")
# Чтение: латиница с тонами, без кириллицы; может быть из нескольких слогов.
PINYIN_RE = re.compile(r"^[a-zA-ZüÜÀ-ɏ̀-ͯ'’\- ]+$")
NUM_PREFIX_RE = re.compile(r"^(?:\d+\)|[а-я]\))\s*")
SENSE_NUM_RE = re.compile(r"(?:^|\s)(?:\d+\)|[а-я]\))")
HAN_RE = re.compile(r"[㐀-鿿豈-﫿]")
# иероглифы, знаки CJK и то, что естественно идёт за ними в примере (?, !, скобки)
ZH_TAIL = re.compile(r"[　-〿㐀-鿿豈-﫿＀-￯]")
SEPARATOR_RE = re.compile(r"^-{3,}$")
ROMAN_READING_RE = re.compile(r"^([IVXL]+)\.?(?:\s*,\s*|\s+)(.+?)\s*[,;]?$")
ROMAN_HEAD_RE = re.compile(r"^[IVXL]+\.?(?:[\s,]|$)")

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


def readings_of(pinyin_line: str, headword: str = "") -> list[str]:
    """«dǎ, dá» → ["dǎ", "dá"]; «wáng; wàng; wǎng; yù» → [...] (бывают оба разделителя).
    У выражения с запятой («不入虎穴，焉得虎子») запятая в пиньине — часть чтения."""
    line = pinyin_line.strip()
    if not line or line == "_":
        return []
    if re.search(r"[,，]", headword):
        return [line]
    return [p.strip() for p in re.split(r"[,;]", line) if p.strip()]


def reading_in_b(content: str) -> tuple[str | None, str | None]:
    """Содержимое [b]…[/b] → (римская цифра раздела, чтение).
    «dǎ» → (None, "dǎ"); «I wáng» / «I, chà» → ("I", …); «II» → (None, None)."""
    c = _clean(content).strip(" ,;")
    m = ROMAN_READING_RE.match(c)
    if m and is_reading(m.group(2)):
        return m.group(1), m.group(2)
    if not m and is_reading(c):
        return None, c
    return None, None


def split_example(text: str) -> tuple[str, str]:
    """«不许打人 нельзя прибегать к побоям» → ("不许打人", "нельзя прибегать к побоям").
    Граница — сразу после последнего иероглифа/знака CJK перед первой кириллицей,
    так что цифры и латиница после иероглифов уходят в перевод. Без иероглифов — ("", текст)."""
    m = CYR_RE.search(text)
    head = text if not m else text[:m.start()]
    last = None
    for i, ch in enumerate(head):
        if ZH_TAIL.match(ch):
            last = i
    if last is None or not HAN_RE.search(head):
        return ("", text.strip()) if m else (text.strip(), "")
    if not m:
        return text.strip(), ""
    cut = last + 1
    # закрывающие скобки и знаки, прилегающие к китайскому тексту, — тоже его часть
    while cut < len(head) and head[cut] in ")]）】?!.,;:…\"'»":
        cut += 1
    return text[:cut].strip(), text[cut:].strip()


# «I», «сущ.», «гл. А», «собств. и усл.» — заголовок раздела, а не значение.
HEAD_RE = re.compile(r"(?:[IVXL]+\.?\s*)?(?:[А-Я]\.?\s*)?(?:[а-яё]{1,8}\.\s*(?:и\s+)?)*(?:[А-Я]\.?)?")


def is_heading(rest: str) -> bool:
    """rest — текст строки без помет [p]. Заголовок: пусто, только пометы, или римская
    цифра раздела без нумерованного значения («I прил. /наречие», «II счётное слово»)."""
    rest = rest.strip()
    return (not rest or bool(HEAD_RE.fullmatch(rest))
            or (bool(ROMAN_HEAD_RE.match(rest)) and not SENSE_NUM_RE.search(rest)))


def _blocks(body: str) -> list[tuple[int, str]]:
    """[mN]…[/m] и текст между ними (как строки уровня 1), без разделителей «-----»."""
    out, pos = [], 0
    for m in M_RE.finditer(body):
        gap = body[pos:m.start()]
        if _clean(gap):
            out.append((1, gap))
        out.append((int(m.group(1)), m.group(2)))
        pos = m.end()
    tail = body[pos:]
    if _clean(tail):
        out.append((1, tail))
    return [(lv, inner) for lv, inner in out if not SEPARATOR_RE.match(_clean(inner))]


def parse_body(body: str, readings: list[str] | None = None) -> list[dict]:
    """Строки статьи: {"level", "kind", "reading", "text"} (+ "zh"/"tr" для примеров).

    text — русский текст без разметки; чтение, совпадающее с заголовком раздела,
    из текста убирается (карточка и так показывает его). readings — чтения статьи из
    строки пиньиня: в БКРС чтение иногда написано прямо в тексте без [b] («1) yīdá дюжина»,
    «I hé, диал. …»)."""
    readings = readings or []
    known = {norm_pinyin(r): r for r in readings} if len(readings) > 1 else {}
    body = body.replace("\\[", _ESC_L).replace("\\]", _ESC_R)
    items: list[dict] = []
    section: str | None = None  # чтение раздела (из заголовка)
    sense: str | None = None  # чтение текущего значения
    sense_level = 0
    for level, inner in _blocks(body):
        is_ex = "[ex]" in inner
        found = [rd for b in B_RE.findall(inner) for rd in [reading_in_b(b)[1]] if rd]
        rd_here = found[0] if found else None
        if rd_here and not is_ex:
            marked = {norm_pinyin(r) for r in found}

            def drop_reading(m: re.Match) -> str:
                roman, rd = reading_in_b(m.group(1))
                if not rd or norm_pinyin(rd) not in marked:
                    return m.group(0)
                return f"[b]{roman}[/b]" if roman else ""  # «I wáng» → раздел «I»

            inner = B_RE.sub(drop_reading, inner)
            inner = re.sub(r"^\s*[,;]\s*", "", inner)
        text = _clean(inner)
        if rd_here and not is_ex:  # «1) [b]nà[/b], (также…)» → «1) (также…)»
            text = re.sub(r"^((?:\d+\)|[а-я]\)|[IVXL]+\.?)?\s*)[,;]\s*",
                          lambda m: m.group(1).rstrip() + " " if m.group(1).strip() else "", text)
        # текст без помет [p] и без римской цифры раздела — для проверки «это заголовок?»
        rest = _clean(re.sub(r"\[p\].*?\[/p\]", "", B_RE.sub(
            lambda m: "" if ROMAN_RE.match(_clean(m.group(1))) else m.group(0), inner)))
        if is_ex:
            zh, tr = split_example(text)
            if not text:
                continue
            reading = sense if sense and level > sense_level else section
            items.append({"level": level, "kind": "ex", "reading": reading, "text": text,
                          "zh": zh, "tr": tr})
            continue
        if known and not rd_here:
            # чтение без [b]: «1) yīdá дюжина» или «I hé, диал. прил.»
            m = re.match(r"^((?:\d+\)|[а-я]\)|[IVXL]+\.?,?)\s*)([^\s,;]+)[,;]?\s+(.*)$", text)
            if m and norm_pinyin(m.group(2)) in known:
                rd_here = known[norm_pinyin(m.group(2))]
                text = f"{m.group(1).strip()} {m.group(3)}".strip()
                rest = _clean(re.sub(r"\[p\].*?\[/p\]", "", text))
        heading = (not text or is_heading(rest)
                   or (bool(ROMAN_HEAD_RE.match(text)) and not SENSE_NUM_RE.search(text)))
        if heading:
            section, sense, sense_level = rd_here, None, 0
            if text:
                items.append({"level": level, "kind": "head", "reading": rd_here, "text": text})
            continue
        if rd_here:
            sense, sense_level = rd_here, level
        elif sense and level <= sense_level:
            sense = None  # новое значение того же уровня — чтение снова от раздела
        items.append({"level": level, "kind": "sense", "reading": sense or section,
                      "text": text})
    # заголовок без своего чтения относится к чтению строк своего раздела
    for i, it in enumerate(items):
        if it["kind"] == "head" and not it["reading"]:
            nxt = next((x for x in items[i + 1:] if x["kind"] != "head"), None)
            if nxt and nxt["reading"]:
                it["reading"] = nxt["reading"]
    return items


def _with_reading(text: str, reading: str) -> str:
    m = NUM_PREFIX_RE.match(text)
    return f"{m.group(0)}{reading} {text[m.end():]}" if m else f"{reading} {text}"


def match_reading(r: str | None, card_readings: list[str]) -> str | None:
    """Чтение БКРС → чтение карточки. При совпадении без учёта регистра предпочитаем
    точное написание, затем обычное чтение, а не фамилию («wáng», а не «Wáng»)."""
    if not r:
        return None
    n = norm_pinyin(r)
    same = [c for c in card_readings if norm_pinyin(c) == n]
    if same:
        exact = [c for c in same if unicodedata.normalize("NFC", c) == unicodedata.normalize("NFC", r)]
        common = [c for c in same if c[:1] == c[:1].lower()]
        return (exact or common or same)[0]
    if strip_tones(r) != n:  # у чтения есть тоны и оно другое (yīdǎ ≠ yīdá)
        return None
    bare = [c for c in card_readings if strip_tones(c) == strip_tones(r)]
    common = [c for c in bare if c[:1] == c[:1].lower()]
    if len(bare) == 1:
        return bare[0]
    return common[0] if len(common) == 1 else None


def assign_readings(items: list[dict], entry_readings: list[str],
                    card_readings: list[str]) -> dict[str, list[dict]]:
    """Распределяет строки статьи по чтениям карточки (ключ — чтение карточки как в
    card_readings). Строки без размеченного чтения:
    - если в статье одно чтение — к нему;
    - иначе — к первому чтению карточки, совпавшему с одним из чтений статьи."""
    default = None
    for r in entry_readings:
        default = match_reading(r, card_readings)
        if default:
            break
    if default is None and card_readings:
        common = [c for c in card_readings if c[:1] == c[:1].lower()]
        default = (common or card_readings)[0]

    out: dict[str, list[dict]] = {}
    for it in items:
        target = match_reading(it["reading"], card_readings) if it["reading"] else None
        if it["reading"] and target is None:
            # чтения нет в карточке — строка идёт к основному чтению, а само чтение
            # остаётся в тексте, как на сайте («2) yīdǎ ударить»)
            target = default
            if it["kind"] == "sense":
                it = {**it, "text": _with_reading(it["text"], it["reading"])}
        out.setdefault(target or default, []).append(it)
    out.pop(None, None)
    return out
