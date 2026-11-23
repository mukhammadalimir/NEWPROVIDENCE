"""Разбор и нормализация пиньиня: "ni hao", "ni3 hao3", "nǐ hǎo", "nǐhǎo" и т.п."""

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from pypinyin import Style, lazy_pinyin
from pypinyin.contrib.tone_convert import to_normal, to_tone
from pypinyin.pinyin_dict import pinyin_dict

_TONE_MARKS = {
    "̄": 1,  # ā
    "́": 2,  # á
    "̌": 3,  # ǎ
    "̀": 4,  # à
}


@lru_cache(maxsize=1)
def syllables() -> frozenset[str]:
    """Все допустимые слоги без тонов (ü записывается как v)."""
    result = set()
    for value in pinyin_dict.values():
        for p in value.split(","):
            s = to_normal(p).replace("ü", "v")
            # Отбрасываем междометия из одних согласных (m, n, ng, hm, r):
            # иначе почти любое латинское слово «разбирается» как пиньинь.
            if re.fullmatch(r"[a-z]+", s) and re.search(r"[aeiouv]", s):
                result.add(s)
    return frozenset(result)


@dataclass(frozen=True)
class Syllable:
    text: str  # без тона, ü = v
    tone: int | None  # 1–5 или None, если тон не указан


def _strip_marks(chunk: str) -> tuple[str, list[int | None]]:
    """Убирает тоновые знаки; возвращает строку и тон для каждого символа."""
    out, tones = [], []
    for ch in unicodedata.normalize("NFD", chunk):
        if ch in _TONE_MARKS:
            if tones:
                tones[-1] = _TONE_MARKS[ch]
            continue
        if ch == "̈":  # ü
            if out and out[-1] == "u":
                out[-1] = "v"
            continue
        out.append(ch)
        tones.append(None)
    return "".join(out), tones


def _segment(word: str) -> list[tuple[int, int]] | None:
    """Делит строку без пробелов на слоги (минимальное количество слогов)."""
    syl = syllables()
    n = len(word)
    best: list[list[tuple[int, int]] | None] = [None] * (n + 1)
    best[0] = []
    for i in range(n):
        if best[i] is None:
            continue
        for j in range(min(n, i + 6), i, -1):
            if word[i:j] in syl:
                cand = best[i] + [(i, j)]
                if best[j] is None or len(cand) < len(best[j]):
                    best[j] = cand
    return best[n]


def parse(text: str) -> list[Syllable] | None:
    """Разбирает строку как пиньинь. None — если это не пиньинь."""
    text = text.strip().lower().replace("u:", "v").replace("ü", "v")
    if not text:
        return None
    result: list[Syllable] = []
    for chunk in re.split(r"[\s'’\-]+", text):
        if not chunk:
            continue
        plain, mark_tones = _strip_marks(chunk)
        # Цифровые тоны: ni3hao3
        parts = re.findall(r"([a-z]+)([1-5]?)", plain)
        if "".join(a + b for a, b in parts) != plain:
            return None
        pos = 0
        for letters, digit in parts:
            seg = _segment(letters)
            if seg is None:
                return None
            for k, (a, b) in enumerate(seg):
                tone = None
                marks = [t for t in mark_tones[pos + a:pos + b] if t]
                if marks:
                    tone = marks[0]
                if digit and k == len(seg) - 1:
                    tone = int(digit)
                result.append(Syllable(letters[a:b], tone))
            pos += len(letters) + len(digit)
    return result or None


def has_tones(syls: list[Syllable]) -> bool:
    return any(s.tone for s in syls)


def toneless_key(syls: list[Syllable]) -> str:
    return "".join(s.text for s in syls)


def tone_key(syls: list[Syllable]) -> str:
    return "".join(f"{s.text}{s.tone or ''}" for s in syls)


def keys_from_numbered(pinyin_num: str) -> tuple[str, str]:
    """"Ni3 hao3" / "lu:4" (формат CC-CEDICT) → ("ni3hao3", "nihao")."""
    s = pinyin_num.lower().replace("u:", "v")
    s = re.sub(r"[^a-z0-9]", "", s)
    return s, re.sub(r"\d", "", s)


def numbered_to_marks(pinyin_num: str) -> str:
    """"ni3 hao3" → "nǐ hǎo"; "lu:4" → "lǜ"; "ma5" → "ma"."""
    out = []
    for token in pinyin_num.split():
        t = token.replace("u:", "v").replace("U:", "V")
        m = re.fullmatch(r"([A-Za-zv]+)([1-5])", t)
        if not m:
            out.append(token)
            continue
        base, tone = m.groups()
        marked = to_tone(base.lower() + tone) if tone != "5" else base.lower().replace("v", "ü")
        if base[0].isupper():
            marked = marked[0].upper() + marked[1:]
        out.append(marked)
    return " ".join(out)


def word_marks(pinyin_num: str) -> str:
    """Пиньинь слова слитно, как в словарях: "xue2 xi2" → "xuéxí", "Zhong1 guo2" → "Zhōngguó"."""
    marked = numbered_to_marks(pinyin_num)
    parts = marked.split()
    if len(parts) > 1 and all(re.fullmatch(r"[^\W\d_]+", p) for p in parts):
        joined = parts[0]
        for p in parts[1:]:
            # апостроф перед слогом на a/o/e: Xī'ān
            joined += ("'" if p[:1].lower() in "aāáǎàoōóǒòeēéěè" else "") + p.lower() \
                if not p[:1].isupper() else " " + p
        return joined
    return marked


def text_to_pinyin(text: str, words: list[str] | None = None) -> str:
    """Пиньинь с тонами для китайского текста (pypinyin, с учётом слов)."""
    parts = words if words is not None else [text]
    out = []
    for w in parts:
        syl = lazy_pinyin(w, style=Style.TONE, errors=lambda x: list(x))
        out.append("".join(syl) if len(w) > 1 and _is_han(w) else " ".join(syl))
    joined = " ".join(p for p in out if p.strip())
    return re.sub(r"\s+([，。！？、,.!?;:])", r"\1", joined)


def _is_han(s: str) -> bool:
    return all("㐀" <= c <= "鿿" for c in s)


# --- Приблизительное звучание для узбекоязычных (только подсказка!) ---

_INITIALS = [
    ("zh", "j"), ("ch", "ch"), ("sh", "sh"), ("b", "b"), ("p", "p"), ("m", "m"),
    ("f", "f"), ("d", "d"), ("t", "t"), ("n", "n"), ("l", "l"), ("g", "g"),
    ("k", "k"), ("h", "x"), ("j", "dj"), ("q", "ch"), ("x", "sh"), ("r", "r"),
    ("z", "dz"), ("c", "ts"), ("s", "s"), ("y", "y"), ("w", "v"),
]
_FINALS = {
    "ian": "yan", "ie": "ye", "iu": "yu", "ui": "uey", "un": "un", "ong": "ung",
    "iong": "yung", "ou": "ou", "ei": "ey", "ai": "ay", "ao": "ao", "eng": "eng",
    "en": "en", "er": "er", "v": "yu", "ve": "yue", "van": "yuan", "vn": "yun",
    "e": "e", "ue": "ue", "uan": "uan",
}


def approx_uz(pinyin_num: str) -> str:
    """Очень приблизительная запись звучания узбекскими буквами."""
    words = []
    for token in pinyin_num.lower().replace("u:", "v").split():
        base = re.sub(r"\d", "", token)
        if not base or not base.isalpha():  # «11» в «Shuang1 11» (双11), латиница и т.п.
            words.append(token)
            continue
        init, rest = "", base
        for a, b in _INITIALS:
            if base.startswith(a):
                init, rest = b, base[len(a):]
                break
        if base[0] in "jqx" and rest.startswith("u"):  # ju/qu/xu = jü/qü/xü
            rest = "v" + rest[1:]
        rest = _FINALS.get(rest, rest)
        words.append(init + rest)
    return " ".join(words)
