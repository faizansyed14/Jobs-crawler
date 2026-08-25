from __future__ import annotations

from contextlib import contextmanager
from typing import Generator, Iterator

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from config.settings import get_settings
from database.models import Base, Job

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine(database_url: str | None = None) -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        url = database_url or get_settings().database_url
        connect_args: dict = {}
        if url.startswith("sqlite"):
            connect_args = {"check_same_thread": False, "timeout": 30}
        _engine = create_engine(
            url,
            future=True,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        if url.startswith("sqlite"):
            from sqlalchemy import event

            @event.listens_for(_engine, "connect")
            def _set_sqlite_pragma(dbapi_connection, connection_record):  # noqa: ARG001
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=30000")
                cursor.close()

        _SessionLocal = sessionmaker(
            bind=_engine, autoflush=False, autocommit=False, future=True
        )
    return _engine


def init_db(database_url: str | None = None) -> None:
    engine = get_engine(database_url)
    Base.metadata.create_all(bind=engine)
    _migrate_schema(engine)


def _migrate_schema(engine: Engine) -> None:
    """Lightweight column/index upgrades for existing SQLite/Postgres DBs."""
    insp = inspect(engine)
    if not insp.has_table("jobs"):
        return
    cols = {c["name"] for c in insp.get_columns("jobs")}
    with engine.begin() as conn:
        if "content_fingerprint" not in cols:
            conn.execute(
                text(
                    "ALTER TABLE jobs ADD COLUMN content_fingerprint VARCHAR(64)"
                )
            )
        dialect = engine.dialect.name
        if dialect == "sqlite":
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_jobs_fingerprint "
                    "ON jobs (source_portal, content_fingerprint)"
                )
            )
        elif dialect == "postgresql":
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_jobs_fingerprint "
                    "ON jobs (source_portal, content_fingerprint)"
                )
            )
    _backfill_fingerprints(engine)


def _backfill_fingerprints(engine: Engine) -> None:
    from core.job_fingerprint import job_content_fingerprint

    with Session(engine) as session:
        rows = list(
            session.execute(
                select(Job).where(Job.content_fingerprint.is_(None)).limit(5000)
            ).scalars()
        )
        updated = False
        for job in rows:
            job.content_fingerprint = job_content_fingerprint(
                source_portal=job.source_portal,
                title=job.title,
                company_name=job.company_name,
                posted_at=job.posted_at,
            )
            updated = True
        if updated:
            session.commit()


@contextmanager
def session_scope() -> Iterator[Session]:
    get_engine()
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Generator[Session, None, None]:
    get_engine()
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()