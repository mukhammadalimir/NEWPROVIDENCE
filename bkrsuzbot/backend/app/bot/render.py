"""Оформление результатов в HTML-сообщения Telegram."""

from html import escape as e

from app.bot.i18n import t

MAX_LEN = 3900  # лимит Telegram — 4096 символов
GLOSS_MARKS = {"mt": " 🤖", "cedict_en": " 📖", "wikt": " 🌐", "bkrs": " 📚", "bkrs_mt": " 📚🤖"}


def bkrs_lines(items: list[dict]) -> list[str]:
    """Строки статьи 大БКРС: значения по порядку словаря, под ними — примеры."""
    out = []
    for it in items:
        if it["kind"] == "head":
            out.append(f"<i>{e(it['text'])}</i>")
        elif it["kind"] == "ex":
            if not it.get("zh"):  # пример без иероглифов — просто текст, один раз
                out.append(f"    ▫️ <i>{e(it.get('tr') or it['text'])}</i>")
                continue
            tr = f" — <i>{e(it['tr'])}</i>" if it.get("tr") else ""
            out.append(f"    ▫️ {e(it['zh'])}{tr}")
        else:
            out.append(e(it["text"]))
    return out


def meaning_lang(result: dict) -> str:
    """На каком языке показываются значения: для uz/ru-ввода — на нём же."""
    src = result.get("source_lang")
    return src if src in ("uz", "ru") else result.get("target_lang", "uz")


def card_text(card: dict, ui: str, lang: str) -> str:
    lines = []
    head = f"<b>{e(card['headword'])}</b>"
    if card.get("traditional"):
        head += f"  ·  {e(card['traditional'])} <i>({t(ui, 'trad')})</i>"
    lines.append(head)
    for r in card["readings"]:
        lines.append("")
        title = f"🔤 <b>{e(r['pinyin'])}</b>"
        if r.get("proper"):
            title += f"  <i>({t(ui, 'proper')})</i>"
        lines.append(title)
        if r.get("approx"):
            lines.append(f"🗣 <i>{t(ui, 'approx')}: «{e(r['approx'])}»</i>")
        if r.get("measure_word"):
            lines.append(f"{t(ui, 'measure')}: {e(r['measure_word'])}")

        senses = r["senses"]
        if r.get("bkrs"):
            # редакционные узбекские значения (написаны человеком) — над переводом БКРС
            senses = [s for s in senses if s["kind"] == "curated"] if lang == "uz" else []
        if senses:
            verified = all(s["verified"] for s in senses)
            src = ("src_wikt" if all(s["kind"] == "wikt" for s in senses)
                   else "src_curated_ok" if verified else "src_curated")
            lines.append(f"<b>{t(ui, 'meanings')}</b> — <i>{t(ui, src)}</i>")
            for i, s in enumerate(senses, 1):
                pos = f"<i>{e(s['pos'])}</i> " if s.get("pos") else ""
                lines.append(f"{i}. {pos}{e(', '.join(s['items']))}")
        if r.get("bkrs"):
            title = t(ui, "meanings") if not senses else "大БКРС"
            lines.append(f"<b>{title}</b> — <i>{t(ui, 'src_' + r['bkrs_kind'])}</i>")
            lines.extend(bkrs_lines(r["bkrs"]))
        if not r.get("bkrs"):  # английские значения — только если нет статьи БКРС
            if r.get("english_mt"):
                lines.append(f"<i>{t(ui, 'src_mt')}:</i> {e('; '.join(r['english_mt'][:6]))}")
            if r.get("english"):
                lines.append(f"<i>{t(ui, 'src_cedict')}:</i> {e('; '.join(r['english'][:6]))}")
            if not r["senses"] and not r.get("english_mt"):
                lines.append(f"<i>{t(ui, 'no_target')}</i>")

        if r.get("usage"):
            lines.append(f"<b>{t(ui, 'usage')}:</b> {e(r['usage']['text'])}")
        if r["collocations"]:
            lines.append(f"<b>{t(ui, 'colloc')}</b>")
            for c in r["collocations"][:6]:
                mark = GLOSS_MARKS.get(c["gloss_kind"], "")
                gloss = f" — {e(c['gloss'])}{mark}" if c.get("gloss") else ""
                lines.append(f"• {e(c['zh'])} <i>{e(c['pinyin'])}</i>{gloss}")
        if r["examples"]:
            lines.append(f"<b>{t(ui, 'examples')}</b>")
            for x in r["examples"][:3]:
                lines.append(f"{e(x['zh'])}\n<i>{e(x['pinyin'])}</i>")
                if x.get("translation"):
                    lines.append(e(x["translation"]))
    return _trim("\n".join(lines))


def ai_text(data: dict, ui: str) -> str:
    lines = [f"<i>{t(ui, 'src_ai')}</i>"]
    if not data.get("known"):
        return lines[0] + "\n" + t(ui, "ai_unknown")
    if data.get("usage"):
        lines.append(f"<b>{t(ui, 'usage')}:</b> {e(data['usage'])}")
    if data.get("examples"):
        lines.append(f"<b>{t(ui, 'examples')}</b>")
        for x in data["examples"]:
            lines.append(f"{e(x['zh'])}\n<i>{e(x['pinyin'])}</i>\n{e(x['translation'])}")
    return _trim("\n".join(lines))


def text_result(result: dict, ui: str) -> str:
    tx = result["text"]
    lines = [f"<b>{t(ui, 'original')}:</b> {e(tx['source'])}"]
    if tx.get("translation") and tx["translation"] != tx["source"]:
        lines.append(f"<b>{t(ui, 'text_title')}:</b> {e(tx['translation'])}")
    lines.append(f"<b>{t(ui, 'pinyin')}:</b> <i>{e(tx['pinyin'])}</i>")
    if tx["words"]:
        lines.append(f"\n<b>{t(ui, 'words')}</b>")
        for w in tx["words"][:12]:
            mark = GLOSS_MARKS.get(w["gloss_kind"], "")
            lines.append(f"• {e(w['zh'])} <i>{e(w['pinyin'])}</i> — {e(w['gloss'])}{mark}")
    return _trim("\n".join(lines))


def notices_text(result: dict, ui: str) -> str:
    out = []
    for n in result.get("notices", []):
        if n == "mt_used" and result.get("mt_headword"):
            out.append(t(ui, "mt_headword", q=e(result["query"]), zh=e(result["mt_headword"])))
        elif n in ("mt_used", "translate_unavailable", "translate_failed"):
            out.append(t(ui, n))
    return "\n".join(out)


def _trim(s: str) -> str:
    return s if len(s) <= MAX_LEN else s[:MAX_LEN].rsplit("\n", 1)[0] + "\n…"
