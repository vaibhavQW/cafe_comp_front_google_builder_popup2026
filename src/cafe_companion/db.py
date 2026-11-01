from collections.abc import Iterator
from datetime import UTC, datetime

import logging
from pathlib import Path

from sqlalchemy import URL, Engine, create_engine, event, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import PROJECT_ROOT, settings

log = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    """Naive UTC timestamp — stored consistently in every backend."""
    return datetime.now(UTC).replace(tzinfo=None)


def _cloud_sql_engine() -> Engine:
    from google.cloud.sql.connector import Connector, IPTypes

    ip_type = IPTypes.PRIVATE if settings.db_ip_type.lower() == "private" else IPTypes.PUBLIC
    connector = Connector(ip_type=ip_type, refresh_strategy="lazy")

    def getconn():
        kwargs = {"user": settings.db_user, "db": settings.db_name}
        if settings.db_iam_auth:
            kwargs["enable_iam_auth"] = True
        else:
            kwargs["password"] = settings.db_pass
        return connector.connect(settings.instance_connection_name, "pg8000", **kwargs)

    return create_engine(
        "postgresql+pg8000://",
        creator=getconn,
        pool_size=5,
        max_overflow=2,
        pool_timeout=30,
        pool_recycle=1800,
        pool_pre_ping=True,
    )


def _sqlite_url(raw: str) -> URL:
    """Resolve relative SQLite paths against the project root (not the CWD) and make
    sure the folder exists — SQLite creates the file itself, but not missing dirs."""
    url = make_url(raw)
    if not url.database or url.database == ":memory:":
        return url
    path = Path(url.database)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        log.info("SQLite database not found — creating %s", path)
    return url.set(database=str(path))


def _url_engine() -> Engine:
    if not settings.database_url.startswith("sqlite"):
        return create_engine(settings.database_url, pool_pre_ping=True)

    eng = create_engine(_sqlite_url(settings.database_url), connect_args={"check_same_thread": False})

    @event.listens_for(eng, "connect")
    def _sqlite_pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")  # honour ON DELETE CASCADE / SET NULL
        cur.execute("PRAGMA journal_mode=WAL")  # readers don't block the writer
        cur.close()

    return eng


engine = _cloud_sql_engine() if settings.instance_connection_name else _url_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
