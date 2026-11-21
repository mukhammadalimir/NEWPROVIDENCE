"""HTTP API для Mini App + раздача собранного фронтенда."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import TgUser, admin_user, current_user
from app.config import Settings, get_settings
from app.db import get_session
from app.models import DictEntry, ErrorReport, FeatureFlag
from app.services import dictionary as dic
from app.services import userdata as ud
from app.services.ai import AIUnavailable
from app.services.container import FLAG_DEFAULTS, Services
from app.services.curated import save_curated
from app.services.search import search
from app.services.tts import TTSUnavailable
from app.text import detect as det
from app.text import pinyin as py


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.services = Services(get_settings())
    yield
    await app.state.services.aclose()


app = FastAPI(title="BKRSUZ API", lifespan=lifespan, docs_url=None, redoc_url=None)


def services(request: Request) -> Services:
    return request.app.state.services


def err(status: int, code: str, **extra):
    return HTTPException(status, {"code": code, **extra})


# ---------- Пользователь ----------

@app.get("/api/health")
async def health():
    return {"ok": True}


@app.get("/api/me")
async def me(user: TgUser = Depends(current_user), s: AsyncSession = Depends(get_session),
             svc: Services = Depends(services), settings: Settings = Depends(get_settings)):
    u = await ud.get_user(s, user.id, user.first_name, user.language_code)
    await s.commit()
    return {
        "id": u.id, "first_name": u.first_name, "ui_lang": u.ui_lang,
        "target_lang": u.target_lang, "voice": u.voice,
        "is_admin": u.id in settings.admin_ids,
        "services": await svc.available(s),
        "voices": svc.tts.voices if svc.tts else [],
        "bot_username": settings.bot_username,
    }


class SettingsIn(BaseModel):
    ui_lang: str | None = None
    target_lang: str | None = None
    voice: str | None = None


@app.put("/api/me/settings")
async def put_settings(body: SettingsIn, user: TgUser = Depends(current_user),
                       s: AsyncSession = Depends(get_session)):
    u = await ud.get_user(s, user.id, user.first_name)
    await ud.update_settings(s, u, ui_lang=body.ui_lang, target_lang=body.target_lang,
                             voice=body.voice)
    return {"ok": True}


@app.delete("/api/me")
async def delete_me(user: TgUser = Depends(current_user), s: AsyncSession = Depends(get_session)):
    await ud.delete_all(s, user.id)
    return {"ok": True}


# ---------- Поиск ----------

class SearchIn(BaseModel):
    q: str = Field(max_length=500)
    source: str | None = None
    target: str | None = None


@app.post("/api/search")
async def api_search(body: SearchIn, user: TgUser = Depends(current_user),
                     s: AsyncSession = Depends(get_session), svc: Services = Depends(services)):
    if not svc.search_limiter.allow(user.id):
        raise err(429, "rate_limited")
    u = await ud.get_user(s, user.id, user.first_name, user.language_code)
    result = await search(s, svc, body.q, user_target=u.target_lang,
                          source=body.source, target=body.target)
    if result["type"] in ("word", "candidates", "text"):
        await ud.add_history(s, u.id, result["query"], result["type"])
        await s.commit()
    favs = {(f["headword"], f["pinyin"]): f["id"] for f in await ud.list_favorites(s, u.id)}
    for card in result.get("cards", []):
        for r in card["readings"]:
            r["favorite_id"] = favs.get((card["headword"], r["pinyin"]))
    return result


@app.get("/api/explain")
async def explain(entry_id: int, lang: str = Query("uz", pattern="^(uz|ru)$"),
                  user: TgUser = Depends(current_user), s: AsyncSession = Depends(get_session),
                  svc: Services = Depends(services)):
    """AI-пояснение и примеры для одного чтения слова (помечаются как AI)."""
    if not (await svc.available(s))["ai"]:
        raise err(503, "ai_unavailable")
    if not svc.ai_limiter.allow(user.id):
        raise err(429, "rate_limited")
    entry = await s.get(DictEntry, entry_id)
    if entry is None:
        raise err(404, "not_found")
    group = await dic.find_by_headword(s, entry.simplified)
    same = [e for e in group if e.pinyin_tone_key == entry.pinyin_tone_key]
    meanings = [d for e in same for sense in e.senses
                for d in (sense.get(lang) or sense.get("en") or [])]
    try:
        data = await svc.ai.explain(s, entry.simplified, py.word_marks(entry.pinyin_num),
                                    meanings, lang)
    except AIUnavailable as e:
        raise err(503, "ai_failed", reason=str(e)) from e
    examples = [{"zh": x["zh"], "pinyin": py.text_to_pinyin(x["zh"]),
                 "translation": x["translation"], "kind": "ai"}
                for x in data.get("examples", [])]
    return {"known": data.get("known", False), "usage": data.get("usage", ""),
            "examples": examples, "kind": "ai"}


@app.get("/api/tts")
async def tts(text: str = Query(max_length=300), slow: bool = False, voice: str | None = None,
              user: TgUser = Depends(current_user), s: AsyncSession = Depends(get_session),
              svc: Services = Depends(services)):
    if not (await svc.available(s))["tts"]:
        raise err(503, "tts_unavailable")
    if not det.HAN_RE.search(text):
        raise err(400, "not_chinese")
    if not svc.tts_limiter.allow(user.id):
        raise err(429, "rate_limited")
    try:
        audio = await svc.tts.synthesize(text, voice, slow, "mp3")
    except TTSUnavailable as e:
        from app.services.events import log_event
        await log_event(s, "tts", False, str(e))
        await s.commit()
        raise err(503, "tts_failed") from e
    return Response(audio, media_type="audio/mpeg",
                    headers={"Cache-Control": "private, max-age=86400"})


# ---------- История, избранное, повторение ----------

@app.get("/api/history")
async def history(user: TgUser = Depends(current_user), s: AsyncSession = Depends(get_session)):
    return await ud.list_history(s, user.id)


@app.delete("/api/history")
async def clear_history(user: TgUser = Depends(current_user),
                        s: AsyncSession = Depends(get_session)):
    await ud.clear_history(s, user.id)
    return {"ok": True}


class FavIn(BaseModel):
    headword: str = Field(max_length=64)
    pinyin: str = Field(max_length=128)
    gloss: str = Field(default="", max_length=500)
    entry_id: int | None = None


@app.get("/api/favorites")
async def favorites(user: TgUser = Depends(current_user), s: AsyncSession = Depends(get_session)):
    return await ud.list_favorites(s, user.id)


@app.post("/api/favorites")
async def add_fav(body: FavIn, user: TgUser = Depends(current_user),
                  s: AsyncSession = Depends(get_session)):
    await ud.get_user(s, user.id, user.first_name)
    return await ud.add_favorite(s, user.id, body.headword, body.pinyin, body.gloss, body.entry_id)


@app.delete("/api/favorites/{fav_id}")
async def del_fav(fav_id: int, user: TgUser = Depends(current_user),
                  s: AsyncSession = Depends(get_session)):
    if not await ud.remove_favorite(s, user.id, fav_id):
        raise err(404, "not_found")
    return {"ok": True}


@app.delete("/api/favorites")
async def clear_favs(user: TgUser = Depends(current_user), s: AsyncSession = Depends(get_session)):
    await ud.clear_favorites(s, user.id)
    return {"ok": True}


@app.get("/api/review/next")
async def review_next(user: TgUser = Depends(current_user),
                      s: AsyncSession = Depends(get_session)):
    return await ud.next_review(s, user.id)


class ReviewIn(BaseModel):
    knew: bool


@app.post("/api/review/{fav_id}")
async def review_answer(fav_id: int, body: ReviewIn, user: TgUser = Depends(current_user),
                        s: AsyncSession = Depends(get_session)):
    if not await ud.answer_review(s, user.id, fav_id, body.knew):
        raise err(404, "not_found")
    return {"ok": True}


class ReportIn(BaseModel):
    query: str = Field(default="", max_length=500)
    message: str = Field(min_length=2, max_length=2000)
    entry_id: int | None = None


@app.post("/api/report")
async def report(body: ReportIn, user: TgUser = Depends(current_user),
                 s: AsyncSession = Depends(get_session)):
    await ud.get_user(s, user.id, user.first_name)
    rep = await ud.add_report(s, user.id, body.query, body.message, body.entry_id)
    return {"ok": True, "id": rep.id}


# ---------- Админ ----------

@app.get("/api/admin/stats")
async def admin_stats(_: TgUser = Depends(admin_user), s: AsyncSession = Depends(get_session),
                      svc: Services = Depends(services)):
    return {**await ud.stats(s), "configured": svc.configured(), "flags": await svc.flags(s)}


@app.get("/api/admin/reports")
async def admin_reports(status: str = "new", _: TgUser = Depends(admin_user),
                        s: AsyncSession = Depends(get_session)):
    rows = (await s.scalars(select(ErrorReport).where(ErrorReport.status == status)
                            .order_by(ErrorReport.id.desc()).limit(100))).all()
    return [{"id": r.id, "user_id": r.user_id, "query": r.query, "message": r.message,
             "entry_id": r.entry_id, "status": r.status, "at": r.created_at.isoformat()}
            for r in rows]


@app.post("/api/admin/reports/{rep_id}/resolve")
async def admin_resolve(rep_id: int, _: TgUser = Depends(admin_user),
                        s: AsyncSession = Depends(get_session)):
    rep = await s.get(ErrorReport, rep_id)
    if rep is None:
        raise err(404, "not_found")
    rep.status = "resolved"
    await s.commit()
    return {"ok": True}


def _entry_dict(e: DictEntry) -> dict:
    return {"id": e.id, "source": e.source, "simplified": e.simplified,
            "traditional": e.traditional, "pinyin": e.pinyin_num, "senses": e.senses,
            "measure_word": e.measure_word, "usage": e.usage, "collocations": e.collocations,
            "examples": e.examples, "verified": e.verified}


@app.get("/api/admin/entries")
async def admin_entries(q: str = Query(min_length=1, max_length=64), _: TgUser = Depends(admin_user),
                        s: AsyncSession = Depends(get_session)):
    rows = (await s.scalars(select(DictEntry).where(
        or_(DictEntry.simplified == q, DictEntry.traditional == q))
        .order_by(DictEntry.source.desc(), DictEntry.id).limit(30))).all()
    return [_entry_dict(e) for e in rows]


class EntryIn(BaseModel):
    simplified: str = Field(min_length=1, max_length=64)
    traditional: str | None = Field(default=None, max_length=64)
    pinyin: str = Field(min_length=1, max_length=128, description='Цифрами: "yu2", "ni3 hao3"')
    senses: list[dict] = Field(default_factory=list)
    measure_word: str | None = None
    usage: dict = Field(default_factory=dict)
    collocations: list[dict] = Field(default_factory=list)
    examples: list[dict] = Field(default_factory=list)
    verified: bool = True


@app.post("/api/admin/entries")
async def admin_create(body: EntryIn, admin: TgUser = Depends(admin_user),
                       s: AsyncSession = Depends(get_session)):
    e = await save_curated(s, None, body.model_dump(), body.verified, admin.id)
    await s.commit()
    return _entry_dict(e)


@app.put("/api/admin/entries/{entry_id}")
async def admin_update(entry_id: int, body: EntryIn, admin: TgUser = Depends(admin_user),
                       s: AsyncSession = Depends(get_session)):
    try:
        e = await save_curated(s, entry_id, body.model_dump(), body.verified, admin.id)
    except ValueError as ex:
        raise err(400, "not_curated") from ex
    await s.commit()
    return _entry_dict(e)


@app.delete("/api/admin/entries/{entry_id}")
async def admin_delete(entry_id: int, _: TgUser = Depends(admin_user),
                       s: AsyncSession = Depends(get_session)):
    res = await s.execute(delete(DictEntry).where(DictEntry.id == entry_id,
                                                  DictEntry.source == "curated"))
    await s.commit()
    if not res.rowcount:
        raise err(404, "not_found")
    return {"ok": True}


class FlagsIn(BaseModel):
    flags: dict[str, bool]


@app.put("/api/admin/flags")
async def admin_flags(body: FlagsIn, _: TgUser = Depends(admin_user),
                      s: AsyncSession = Depends(get_session), svc: Services = Depends(services)):
    for key, enabled in body.flags.items():
        if key in FLAG_DEFAULTS:
            await s.merge(FeatureFlag(key=key, enabled=enabled))
    await s.commit()
    return await svc.flags(s)


# ---------- Фронтенд Mini App ----------

DIST = Path(os.getenv("MINIAPP_DIST", Path(__file__).resolve().parents[3] / "miniapp" / "dist"))
if DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith("api/"):
            raise err(404, "not_found")
        return FileResponse(DIST / "index.html")
