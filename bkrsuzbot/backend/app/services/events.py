from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ServiceEvent


async def log_event(session: AsyncSession, service: str, ok: bool, detail: str = "") -> None:
    """Записывает событие для статистики админа (коммит — на стороне вызывающего)."""
    session.add(ServiceEvent(service=service, ok=ok, detail=detail[:300]))
