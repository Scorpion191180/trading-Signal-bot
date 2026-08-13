"""Engine- und Session-Erzeugung ohne globale Datenbankverbindung."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

SQLITE_COMPATIBILITY_COLUMNS = {
    "virtual_positions": {
        "entry_provider": "VARCHAR(80) NOT NULL DEFAULT 'unbekannt'",
        "last_provider": "VARCHAR(80) NOT NULL DEFAULT 'unbekannt'",
        "entry_news_factor": "FLOAT NOT NULL DEFAULT 0.5",
        "entry_news_ids": "TEXT NOT NULL DEFAULT ''",
        "is_demo": "BOOLEAN NOT NULL DEFAULT 0",
    },
    "virtual_orders": {
        "provider": "VARCHAR(80) NOT NULL DEFAULT 'unbekannt'",
        "is_demo": "BOOLEAN NOT NULL DEFAULT 0",
    },
    "trades": {
        "entry_provider": "VARCHAR(80) NOT NULL DEFAULT 'unbekannt'",
        "exit_provider": "VARCHAR(80) NOT NULL DEFAULT 'unbekannt'",
        "entry_news_factor": "FLOAT NOT NULL DEFAULT 0.5",
        "exit_news_factor": "FLOAT NOT NULL DEFAULT 0.5",
        "entry_news_ids": "TEXT NOT NULL DEFAULT ''",
        "exit_news_ids": "TEXT NOT NULL DEFAULT ''",
        "is_demo": "BOOLEAN NOT NULL DEFAULT 0",
    },
    "signals": {
        "news_factor": "FLOAT NOT NULL DEFAULT 0.5",
        "news_ids": "TEXT NOT NULL DEFAULT ''",
    },
    "news": {
        "summary": "TEXT NOT NULL DEFAULT ''",
        "url": "TEXT NOT NULL DEFAULT ''",
        "credibility": "FLOAT NOT NULL DEFAULT 0.5",
        "direct_relevance": "BOOLEAN NOT NULL DEFAULT 1",
        "possibly_priced_in": "BOOLEAN NOT NULL DEFAULT 0",
        "related_symbols": "TEXT NOT NULL DEFAULT ''",
        "fetched_at": "DATETIME",
    },
}


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
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()
    Base.metadata.create_all(engine)
    if engine.dialect.name == "sqlite":
        inspector = inspect(engine)
        with engine.begin() as connection:
            for table_name, definitions in SQLITE_COMPATIBILITY_COLUMNS.items():
                if not inspector.has_table(table_name):
                    continue
                existing = {column["name"] for column in inspector.get_columns(table_name)}
                for column_name, definition in definitions.items():
                    if column_name not in existing:
                        connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"))
    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
