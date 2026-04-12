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
