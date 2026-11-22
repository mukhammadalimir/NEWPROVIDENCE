from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

_url = get_settings().database_url
IS_SQLITE = _url.startswith("sqlite")

engine = create_async_engine(
    _url,
    pool_pre_ping=not IS_SQLITE,
    # SQLite: ждать до 30 с, если файл занят другим процессом (бот + API).
    connect_args={"timeout": 30} if IS_SQLITE else {},
)

if IS_SQLITE:
    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")  # ON DELETE CASCADE / SET NULL
        cur.execute("PRAGMA journal_mode=WAL")  # чтение не блокируется записью
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
