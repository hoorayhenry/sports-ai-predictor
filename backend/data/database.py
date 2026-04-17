from contextlib import asynccontextmanager, contextmanager
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from data.db_models.models import Base
from config.settings import get_settings

settings = get_settings()
_is_sqlite = settings.database_url.startswith("sqlite")
_async_kw = {"echo": settings.debug}
_sync_kw = {"echo": settings.debug}
if _is_sqlite:
    _async_kw["connect_args"] = {"check_same_thread": False}
    _sync_kw["connect_args"] = {"check_same_thread": False}
else:
    _async_kw.update({"pool_pre_ping": True, "pool_size": 10, "max_overflow": 20})
    _sync_kw.update({"pool_pre_ping": True, "pool_size": 5})

async_engine = create_async_engine(settings.database_url, **_async_kw)
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)

sync_engine = create_engine(settings.database_url_sync, **_sync_kw)
SyncSessionLocal = sessionmaker(bind=sync_engine, autoflush=False, autocommit=False)


async def init_db():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_migrations(conn)


async def _run_migrations(conn) -> None:
    """
    Safe incremental migrations for existing databases.
    Only adds missing columns — never drops or alters existing ones.
    Compatible with SQLite and PostgreSQL.
    """
    from sqlalchemy import text

    is_sqlite = str(conn.engine.url).startswith("sqlite")

    if is_sqlite:
        # SQLite: check via PRAGMA table_info
        result = await conn.execute(text("PRAGMA table_info(news_articles)"))
        existing_cols = {row[1] for row in result.fetchall()}
        if "status" not in existing_cols:
            await conn.execute(
                text("ALTER TABLE news_articles ADD COLUMN status VARCHAR(16) DEFAULT 'published'")
            )

        result = await conn.execute(text("PRAGMA table_info(participants)"))
        participant_cols = {row[1] for row in result.fetchall()}
        if "api_football_id" not in participant_cols:
            await conn.execute(
                text("ALTER TABLE participants ADD COLUMN api_football_id INTEGER")
            )
    else:
        # PostgreSQL: check information_schema
        result = await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='news_articles' AND column_name='status'"
        ))
        if not result.fetchone():
            await conn.execute(
                text("ALTER TABLE news_articles ADD COLUMN status VARCHAR(16) DEFAULT 'published'")
            )

        result = await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='participants' AND column_name='api_football_id'"
        ))
        if not result.fetchone():
            await conn.execute(
                text("ALTER TABLE participants ADD COLUMN api_football_id INTEGER")
            )


def init_db_sync():
    Base.metadata.create_all(bind=sync_engine)


async def get_async_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# Legacy alias
get_db = get_async_session


@contextmanager
def get_sync_session():
    session = SyncSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
