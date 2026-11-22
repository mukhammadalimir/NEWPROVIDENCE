"""Извлечение пар «русское/узбекское слово → китайское слово» из Wiktionary.

Источник — выгрузки wiktextract с kaikki.org (данные Wiktionary, CC BY-SA 4.0):
  * английский Wiktionary: в таблицах переводов одного значения английского слова
    стоят переводы на русский, узбекский и китайский (путунхуа) — связываем их
    между собой по этому значению;
  * русский Wiktionary: у русских слов есть переводы на китайский (и на узбекский
    в том же значении — связываем так же).

Скрипт читает файлы потоком (stdin или --file, .jsonl или .jsonl.gz) и пишет TSV:
  lang  word  zh  sense  source
Пример:
  curl -s https://kaikki.org/dictionary/English/kaikki.org-dictionary-English.jsonl \
    | python -m app.scripts.extract_wiktionary --kind en > wikt_en.tsv
  curl -s https://kaikki.org/dictionary/downloads/ru/ru-extract.jsonl.gz | gunzip \
    | python -m app.scripts.extract_wiktionary --kind ru > wikt_ru.tsv
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import unicodedata

HAN_RE = re.compile(r"^[㐀-鿿豈-﫿]+$")
# Диалекты, которые нельзя выдавать за путунхуа
DIALECT_TAGS = {
    "Cantonese", "Hokkien", "Hakka", "Teochew", "Wu", "Min", "Gan", "Xiang", "Jin",
    "Taiwanese", "Shanghainese", "Dungan", "Classical", "Literary", "Min-Nan", "Min-Dong",
}


def clean_word(w: str) -> str:
    # убираем знаки ударения (о́сень → осень), лишние пробелы
    w = unicodedata.normalize("NFD", w)
    w = "".join(ch for ch in w if ch not in "́̀")
    w = unicodedata.normalize("NFC", w).strip()
    return re.sub(r"\s+", " ", w)


def is_mandarin(t: dict) -> bool:
    if t.get("lang_code") not in ("zh", "cmn"):
        return False
    lang = t.get("lang", "")
    tags = set(t.get("tags") or [])
    if tags & DIALECT_TAGS:
        return False
    if lang in ("Chinese Mandarin", "Mandarin", "Китайский", "Chinese"):
        return True
    return False


def zh_words(t: dict) -> list[str]:
    w = (t.get("word") or "").strip()
    out = []
    for part in re.split(r"[,，/;；]\s*", w):
        part = part.strip()
        if part and HAN_RE.match(part) and len(part) <= 6:
            out.append(part)
    return out


def all_translations(d: dict):
    yield from d.get("translations") or []
    for s in d.get("senses") or []:
        yield from s.get("translations") or []


def open_input(path: str | None):
    if not path or path == "-":
        return sys.stdin
    if path.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, encoding="utf-8")


def run_en(f, out):
    for line in f:
        # быстрый отсев: без китайского и без русского/узбекского перевода строку не разбираем
        if '"lang_code": "zh"' not in line or ('"lang_code": "ru"' not in line and '"lang_code": "uz"' not in line):
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("lang_code") != "en":
            continue
        by_sense: dict[str, dict[str, set]] = {}
        for t in all_translations(d):
            code = t.get("lang_code")
            if code not in ("ru", "uz", "zh", "cmn"):
                continue
            key = t.get("sense") or ""
            slot = by_sense.setdefault(key, {"ru": set(), "uz": set(), "zh": set()})
            if code in ("zh", "cmn"):
                if is_mandarin(t):
                    slot["zh"].update(zh_words(t))
            else:
                w = clean_word(t.get("word") or "")
                if w and len(w) <= 40:
                    slot[code].add(w)
        en = d.get("word", "")
        for sense, slot in by_sense.items():
            if not slot["zh"]:
                continue
            gloss = f"{en}: {sense}" if sense else en
            for lang in ("ru", "uz"):
                for w in slot[lang]:
                    for zh in slot["zh"]:
                        out.write(f"{lang}\t{w}\t{zh}\t{gloss}\ten\n")


def run_ru(f, out):
    for line in f:
        if '"lang_code": "zh"' not in line and '"lang_code": "cmn"' not in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("lang_code") != "ru":
            continue
        w = clean_word(d.get("word") or "")
        if not w or len(w) > 40:
            continue
        by_sense: dict[str, dict[str, set]] = {}
        for t in all_translations(d):
            key = (t.get("sense") or "").replace("\t", " ")
            slot = by_sense.setdefault(key, {"uz": set(), "zh": set()})
            if is_mandarin(t):
                slot["zh"].update(zh_words(t))
            elif t.get("lang_code") == "uz":
                u = clean_word(t.get("word") or "")
                if u and len(u) <= 40:
                    slot["uz"].add(u)
        for sense, slot in by_sense.items():
            for zh in slot["zh"]:
                out.write(f"ru\t{w}\t{zh}\t{sense}\tru\n")
                # узбекский перевод того же значения русского слова
                for u in slot["uz"]:
                    out.write(f"uz\t{u}\t{zh}\t{w}: {sense}\tru\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["en", "ru"], required=True)
    ap.add_argument("--file")
    a = ap.parse_args()
    f = open_input(a.file)
    (run_en if a.kind == "en" else run_ru)(f, sys.stdout)


if __name__ == "__main__":
    main()
