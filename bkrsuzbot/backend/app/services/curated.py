"""Создание/изменение редакционных карточек (используют seed и админка)."""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DictEntry, DictGloss
from app.text import uzbek
from app.text.pinyin import keys_from_numbered


def _terms(lang: str, items: list[str]) -> set[str]:
    out = set()
    for item in items:
        for part in item.split(","):
            t = uzbek.normalize(part) if lang == "uz" else part.lower().strip(" .,!?")
            if t:
                out.add(t)
    return out


async def save_curated(session: AsyncSession, entry_id: int | None, data: dict,
                       verified: bool, editor_id: int | None = None) -> DictEntry:
    tone_key, key = keys_from_numbered(data["pinyin"])
    if entry_id:
        entry = await session.get(DictEntry, entry_id)
        if entry is None or entry.source != "curated":
            raise ValueError("not a curated entry")
    else:
        entry = DictEntry(source="curated")
        session.add(entry)
    entry.simplified = data["simplified"].strip()
    entry.traditional = (data.get("traditional") or data["simplified"]).strip()
    entry.pinyin_num = data["pinyin"].strip()
    entry.pinyin_tone_key, entry.pinyin_key = tone_key, key
    entry.senses = data.get("senses", [])
    entry.measure_word = data.get("measure_word") or None
    entry.usage = data.get("usage", {})
    entry.collocations = data.get("collocations", [])
    entry.examples = data.get("examples", [])
    entry.verified = verified
    entry.updated_by = editor_id
    if not entry.freq:
        cedict_freq = await session.scalar(select(DictEntry.freq).where(
            DictEntry.source == "cedict", DictEntry.simplified == entry.simplified).limit(1))
        entry.freq = cedict_freq or 0
    await session.flush()
    await session.execute(delete(DictGloss).where(DictGloss.entry_id == entry.id))
    for lang in ("uz", "ru"):
        terms = set()
        for s in entry.senses:
            terms |= _terms(lang, s.get(lang, []))
        for t in terms:
            session.add(DictGloss(entry_id=entry.id, lang=lang, term=t[:128]))
    return entry
