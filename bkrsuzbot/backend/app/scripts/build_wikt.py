"""Сборка словаря «русский/узбекский → китайский» из пар Wiktionary.

Вход: TSV от app/scripts/extract_wiktionary.py (lang, word, zh, sense, source) и
cedict.json из app/scripts/export_offline.py (чтобы оставить только слова, которые есть
в CC-CEDICT, и привести традиционные иероглифы к упрощённым).

Выход: JSON {"license": ..., "ru": {слово: "zh1|zh2|..."}, "uz": {...}} —
китайские слова упорядочены по числу подтверждений в Wiktionary, затем по частотности.

  python -m app.scripts.build_wikt --cedict ../webapp/data/cedict.json \
      --out ../webapp/data/wikt.json wikt_en.tsv wikt_ru.tsv
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict

LICENSE = (
    "Переводы ru/uz ↔ zh: Wiktionary (en.wiktionary.org, ru.wiktionary.org), "
    "CC BY-SA 4.0, извлечено wiktextract (kaikki.org). Не проверено редакцией."
)
APOS = re.compile(r"[ʻʼ‘’`´ʹ]")
CYR_UZ = re.compile(r"[а-яА-ЯёЁўқғҳЎҚҒҲ]")


def norm(lang: str, w: str) -> str:
    w = w.strip().lower()
    if lang == "ru":
        w = w.replace("ё", "е")
    else:
        if CYR_UZ.search(w):
            return ""  # узбекская кириллица в Wiktionary редка; поиск переводит её в латиницу сам
        w = APOS.sub("'", w)
    w = re.sub(r"\s+", " ", w)
    w = re.sub(r"^[ .,!?;:()\-]+|[ .,!?;:()\-]+$", "", w)
    if not w or len(w) > 40 or re.search(r"[0-9\[\]{}<>=/\\|]", w):
        return ""
    return w


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cedict", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--per-word", type=int, default=6)
    ap.add_argument("tsv", nargs="+")
    a = ap.parse_args()

    simp_freq: dict[str, int] = {}
    trad2simp: dict[str, str] = {}
    proper_only: set[str] = set()
    common: set[str] = set()
    for simp, trad, pin, _defs, _mw, freq in json.load(open(a.cedict, encoding="utf-8")):
        simp_freq[simp] = max(simp_freq.get(simp, 0), freq or 0)
        if trad and trad != simp:
            trad2simp.setdefault(trad, simp)
        if pin[:1].isupper():
            proper_only.add(simp)
        else:
            common.add(simp)
    proper_only -= common

    votes: dict[tuple[str, str], dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for path in a.tsv:
        for line in open(path, encoding="utf-8"):
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 5:
                continue
            lang, word, zh, sense, src = parts
            w = norm(lang, word)
            if not w:
                continue
            if zh not in simp_freq:
                zh = trad2simp.get(zh, "")
            if not zh or zh in proper_only:
                continue
            votes[(lang, w)][zh].add(f"{src}:{sense}")

    out = {"license": LICENSE, "ru": {}, "uz": {}}
    for (lang, w), zhs in votes.items():
        ranked = sorted(zhs, key=lambda z: (-len(zhs[z]), -simp_freq.get(z, 0), len(z)))
        out[lang][w] = "|".join(ranked[: a.per_word])
    for lang in ("ru", "uz"):
        out[lang] = dict(sorted(out[lang].items()))
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print({lang: len(out[lang]) for lang in ("ru", "uz")})


if __name__ == "__main__":
    main()
