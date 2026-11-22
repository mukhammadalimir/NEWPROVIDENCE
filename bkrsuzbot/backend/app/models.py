"""Схема базы данных. Миграции — в alembic/versions."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class DictEntry(Base):
    """Словарная статья: одно написание + одно чтение.

    source = "cedict"  — CC-CEDICT (китайско-английский, CC BY-SA 4.0);
    source = "curated" — карточка редакции с узбекскими/русскими значениями.
    Если у иероглифа несколько чтений, это несколько строк — значения не смешиваются.
    """

    __tablename__ = "dict_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(16), index=True)
    simplified: Mapped[str] = mapped_column(String(64), index=True)
    traditional: Mapped[str] = mapped_column(String(64), index=True)
    pinyin_num: Mapped[str] = mapped_column(String(128))  # "yu2", "ni3 hao3"
    pinyin_tone_key: Mapped[str] = mapped_column(String(128), index=True)  # "ni3hao3"
    pinyin_key: Mapped[str] = mapped_column(String(128), index=True)  # "nihao"
    # [{"pos": "ot", "en": [...], "uz": [...], "ru": [...]}]
    senses: Mapped[list] = mapped_column(JSON, default=list)
    measure_word: Mapped[str | None] = mapped_column(String(64))
    usage: Mapped[dict] = mapped_column(JSON, default=dict)  # {"uz": "...", "ru": "..."}
    # [{"zh", "pinyin", "uz", "ru"}]
    collocations: Mapped[list] = mapped_column(JSON, default=list)
    examples: Mapped[list] = mapped_column(JSON, default=list)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    freq: Mapped[int] = mapped_column(Integer, default=0)
    updated_by: Mapped[int | None] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DictGloss(Base):
    """Обратный индекс узбекских/русских значений редакционных карточек."""

    __tablename__ = "dict_glosses"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("dict_entries.id", ondelete="CASCADE"))
    lang: Mapped[str] = mapped_column(String(4))
    term: Mapped[str] = mapped_column(String(128))

    __table_args__ = (Index("ix_dict_glosses_lang_term", "lang", "term"),)


class WiktPair(Base):
    """Wiktionary (CC BY-SA 4.0): слово ru/uz → китайское слово; rank 0 — самый прямой перевод.

    Данные не проверены редакцией и помечаются в выдаче как «wikt»."""

    __tablename__ = "wikt_pairs"

    id: Mapped[int] = mapped_column(primary_key=True)
    lang: Mapped[str] = mapped_column(String(4))
    term: Mapped[str] = mapped_column(String(64))
    zh: Mapped[str] = mapped_column(String(16))
    rank: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (Index("ix_wikt_lang_term", "lang", "term"), Index("ix_wikt_lang_zh", "lang", "zh"))


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram user id
    first_name: Mapped[str] = mapped_column(String(128), default="")
    ui_lang: Mapped[str] = mapped_column(String(4), default="uz")  # uz | ru
    target_lang: Mapped[str] = mapped_column(String(4), default="uz")  # язык перевода с китайского
    voice: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SearchHistory(Base):
    __tablename__ = "search_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    query: Mapped[str] = mapped_column(String(500))
    kind: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Favorite(Base):
    __tablename__ = "favorites"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    headword: Mapped[str] = mapped_column(String(64))
    pinyin: Mapped[str] = mapped_column(String(128))
    gloss: Mapped[str] = mapped_column(Text, default="")
    entry_id: Mapped[int | None] = mapped_column(ForeignKey("dict_entries.id", ondelete="SET NULL"))
    box: Mapped[int] = mapped_column(Integer, default=1)  # коробка Лейтнера для повторения
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("user_id", "headword", "pinyin", name="uq_fav"),)


class ErrorReport(Base):
    __tablename__ = "error_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    query: Mapped[str] = mapped_column(String(500), default="")
    entry_id: Mapped[int | None] = mapped_column(ForeignKey("dict_entries.id", ondelete="SET NULL"))
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="new")  # new | resolved
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ServiceEvent(Base):
    """Журнал для статистики: запросы и ошибки внешних сервисов."""

    __tablename__ = "service_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    service: Mapped[str] = mapped_column(String(16))  # search | translate | tts | ai
    ok: Mapped[bool] = mapped_column(Boolean)
    detail: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True)


class FeatureFlag(Base):
    __tablename__ = "feature_flags"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class CacheItem(Base):
    """Кэш машинного перевода и AI-ответов (ключ — sha256 запроса)."""

    __tablename__ = "cache_items"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    value: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BotPayload(Base):
    """Короткие ссылки для callback-кнопок бота (лимит Telegram — 64 байта)."""

    __tablename__ = "bot_payloads"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
