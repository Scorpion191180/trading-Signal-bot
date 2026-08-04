"""Engine- und Session-Erzeugung ohne globale Datenbankverbindung."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


def _prepare_sqlite_path(database_url: str) -> None:
    if database_url.startswith("sqlite:///") and database_url != "sqlite:///:memory:":
        Path(database_url.removeprefix("sqlite:///")).expanduser().parent.mkdir(parents=True, exist_ok=True)


def create_database(database_url: str) -> Engine:
    _prepare_sqlite_path(database_url)
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args, future=True)
    if database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection: object, _connection_record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    Base.metadata.create_all(engine)
    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
