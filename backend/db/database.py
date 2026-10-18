from collections.abc import AsyncGenerator
import os
from pathlib import Path

from fastapi import Depends
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy import inspect, text, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from backend.db_models.assets import Base, User, OAuthAccount

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./walletdatabase.db")

# A relative sqlite path like ./walletdatabase.db would depend on the folder the server was started from,
# so anchor it to the project root to always use the same database file
if DATABASE_URL.startswith("sqlite+aiosqlite:///./"):
    DATABASE_URL = "sqlite+aiosqlite:///" + (PROJECT_ROOT / DATABASE_URL.removeprefix("sqlite+aiosqlite:///./")).as_posix()

engine = create_async_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # required for SQLite
    pool_size=1,  # SQLite only supports 1 real writer at a time
    max_overflow=0,
    pool_timeout=60,
)

async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


# Columns added to existing tables after the first release. create_all() only creates missing *tables*, so the
# production database (made before these columns existed) gets them here, once, with ALTER TABLE ADD COLUMN.
# Add new columns as {table: {column: "SQL type and default"}}; keep the model and this list in step.
ADDED_COLUMNS: dict[str, dict[str, str]] = {}


def _add_missing_columns(sync_conn):
    inspector = inspect(sync_conn)
    for table, columns in ADDED_COLUMNS.items():
        if not inspector.has_table(table):
            continue  # brand new database: create_all just made it with every column
        existing = {col["name"] for col in inspector.get_columns(table)}
        for name, ddl in columns.items():
            if name not in existing:
                sync_conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {ddl}'))


async def create_db_and_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)
        # Google tokens used to be saved with linked accounts but were never used again; blank any left over
        await conn.execute(update(OAuthAccount).where(OAuthAccount.access_token != "")
                           .values(access_token="", refresh_token=None, expires_at=None))


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


async def get_user_db(session: AsyncSession = Depends(get_async_session)):
    yield SQLAlchemyUserDatabase(session, User, OAuthAccount)
