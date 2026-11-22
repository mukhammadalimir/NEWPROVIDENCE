"""Данные пользователя: настройки, история, избранное, повторение, сообщения об ошибках.

Все функции принимают user_id из проверенного источника (Telegram update или
проверенный initData) — данные разных пользователей не пересекаются.
"""

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    BotPayload,
    ErrorReport,
    Favorite,
    SearchHistory,
    ServiceEvent,
    User,
)

LANGS = ("uz", "ru")
HISTORY_LIMIT = 50
REVIEW_INTERVALS = [0, 1, 3, 7, 14, 30]  # дни для коробок Лейтнера 1..5


def now() -> datetime:
    return datetime.now(timezone.utc)


async def get_user(session: AsyncSession, user_id: int, first_name: str = "",
                   lang_hint: str | None = None) -> User:
    user = await session.get(User, user_id)
    if user is None:
        lang = "ru" if (lang_hint or "").startswith("ru") else "uz"
        user = User(id=user_id, first_name=first_name[:128], ui_lang=lang, target_lang=lang)
        session.add(user)
        await session.flush()
    else:
        user.last_seen = now()
    return user


async def update_settings(session: AsyncSession, user: User, *, ui_lang=None, target_lang=None,
                          voice=None) -> User:
    if ui_lang in LANGS:
        user.ui_lang = ui_lang
    if target_lang in LANGS:
        user.target_lang = target_lang
    if voice is not None:
        user.voice = voice[:64]
    await session.commit()
    return user


# --- История ---

async def add_history(session: AsyncSession, user_id: int, query: str, kind: str) -> None:
    session.add(SearchHistory(user_id=user_id, query=query[:500], kind=kind))
    await session.flush()
    # Храним только последние записи.
    old = (await session.scalars(
        select(SearchHistory.id).where(SearchHistory.user_id == user_id)
        .order_by(SearchHistory.id.desc()).offset(HISTORY_LIMIT))).all()
    if old:
        await session.execute(delete(SearchHistory).where(SearchHistory.id.in_(old)))


async def list_history(session: AsyncSession, user_id: int, limit: int = 30) -> list[dict]:
    rows = (await session.scalars(
        select(SearchHistory).where(SearchHistory.user_id == user_id)
        .order_by(SearchHistory.id.desc()).limit(limit * 2))).all()
    seen, out = set(), []
    for r in rows:
        if r.query in seen:
            continue
        seen.add(r.query)
        out.append({"query": r.query, "kind": r.kind, "at": r.created_at.isoformat()})
    return out[:limit]


async def clear_history(session: AsyncSession, user_id: int) -> None:
    await session.execute(delete(SearchHistory).where(SearchHistory.user_id == user_id))
    await session.commit()


# --- Избранное и повторение ---

def _fav_dict(f: Favorite) -> dict:
    return {"id": f.id, "headword": f.headword, "pinyin": f.pinyin, "gloss": f.gloss,
            "entry_id": f.entry_id, "box": f.box, "due_at": f.due_at.isoformat()}


async def add_favorite(session: AsyncSession, user_id: int, headword: str, pinyin: str,
                       gloss: str, entry_id: int | None) -> dict:
    existing = await session.scalar(select(Favorite).where(
        Favorite.user_id == user_id, Favorite.headword == headword, Favorite.pinyin == pinyin))
    if existing:
        return _fav_dict(existing)
    fav = Favorite(user_id=user_id, headword=headword[:64], pinyin=pinyin[:128],
                   gloss=gloss[:500], entry_id=entry_id, due_at=now())
    session.add(fav)
    await session.commit()
    return _fav_dict(fav)


async def remove_favorite(session: AsyncSession, user_id: int, fav_id: int) -> bool:
    res = await session.execute(
        delete(Favorite).where(Favorite.id == fav_id, Favorite.user_id == user_id))
    await session.commit()
    return res.rowcount > 0


async def find_favorite(session: AsyncSession, user_id: int, headword: str,
                        pinyin: str) -> Favorite | None:
    return await session.scalar(select(Favorite).where(
        Favorite.user_id == user_id, Favorite.headword == headword, Favorite.pinyin == pinyin))


async def list_favorites(session: AsyncSession, user_id: int) -> list[dict]:
    rows = (await session.scalars(select(Favorite).where(Favorite.user_id == user_id)
                                  .order_by(Favorite.id.desc()))).all()
    return [_fav_dict(f) for f in rows]


async def clear_favorites(session: AsyncSession, user_id: int) -> None:
    await session.execute(delete(Favorite).where(Favorite.user_id == user_id))
    await session.commit()


async def next_review(session: AsyncSession, user_id: int) -> dict | None:
    """Следующая карточка для повторения: сначала «просроченные», затем любые."""
    fav = await session.scalar(
        select(Favorite).where(Favorite.user_id == user_id, Favorite.due_at <= now())
        .order_by(Favorite.box, Favorite.due_at).limit(1))
    if fav is None:
        fav = await session.scalar(select(Favorite).where(Favorite.user_id == user_id)
                                   .order_by(Favorite.due_at).limit(1))
    if fav is None:
        return None
    total = await session.scalar(select(func.count()).select_from(Favorite).where(
        Favorite.user_id == user_id, Favorite.due_at <= now()))
    return {**_fav_dict(fav), "due_count": total or 0}


async def answer_review(session: AsyncSession, user_id: int, fav_id: int, knew: bool) -> bool:
    fav = await session.scalar(select(Favorite).where(
        Favorite.id == fav_id, Favorite.user_id == user_id))
    if fav is None:
        return False
    fav.box = min(fav.box + 1, len(REVIEW_INTERVALS) - 1) if knew else 1
    fav.due_at = now() + timedelta(days=REVIEW_INTERVALS[fav.box])
    await session.commit()
    return True


# --- Удаление всех данных ---

async def delete_all(session: AsyncSession, user_id: int) -> None:
    """Удаляет пользователя; история и избранное удаляются каскадно."""
    await session.execute(delete(SearchHistory).where(SearchHistory.user_id == user_id))
    await session.execute(delete(Favorite).where(Favorite.user_id == user_id))
    await session.execute(delete(User).where(User.id == user_id))
    await session.commit()


# --- Сообщения об ошибках ---

async def add_report(session: AsyncSession, user_id: int | None, query: str, message: str,
                     entry_id: int | None = None) -> ErrorReport:
    rep = ErrorReport(user_id=user_id, query=query[:500], message=message[:2000],
                      entry_id=entry_id)
    session.add(rep)
    await session.commit()
    return rep


# --- Короткие ссылки для кнопок бота ---

async def put_payload(session: AsyncSession, data: dict) -> str:
    pid = secrets.token_urlsafe(6)[:8]
    session.add(BotPayload(id=pid, data=data))
    await session.flush()
    return pid


async def get_payload(session: AsyncSession, pid: str) -> dict | None:
    p = await session.get(BotPayload, pid)
    return p.data if p else None


# --- Статистика для админа ---

async def stats(session: AsyncSession, days: int = 7) -> dict:
    since = now() - timedelta(days=days)
    users_total = await session.scalar(select(func.count()).select_from(User))
    users_active = await session.scalar(
        select(func.count()).select_from(User).where(User.last_seen >= since))
    rows = (await session.execute(
        select(ServiceEvent.service, ServiceEvent.ok, func.count())
        .where(ServiceEvent.created_at >= since)
        .group_by(ServiceEvent.service, ServiceEvent.ok))).all()
    services: dict[str, dict] = {}
    for service, ok, n in rows:
        services.setdefault(service, {"ok": 0, "error": 0})["ok" if ok else "error"] += n
    last_errors = (await session.scalars(
        select(ServiceEvent).where(ServiceEvent.ok.is_(False))
        .order_by(ServiceEvent.id.desc()).limit(10))).all()
    reports_new = await session.scalar(
        select(func.count()).select_from(ErrorReport).where(ErrorReport.status == "new"))
    return {
        "days": days, "users_total": users_total or 0, "users_active": users_active or 0,
        "services": services, "reports_new": reports_new or 0,
        "last_errors": [{"service": e.service, "detail": e.detail,
                         "at": e.created_at.isoformat()} for e in last_errors],
    }
