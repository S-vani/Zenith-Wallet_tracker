from collections.abc import AsyncGenerator
import os
from pathlib import Path

from fastapi import Depends
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy import event, inspect, text, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from backend.db_models.assets import Base, User, OAuthAccount

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./walletdatabase.db")

# A relative sqlite path like ./walletdatabase.db would depend on the folder the server was started from,
# so anchor it to the project root to always use the same database file
if DATABASE_URL.startswith("sqlite+aiosqlite:///./"):
    DATABASE_URL = "sqlite+aiosqlite:///" + (PROJECT_ROOT / DATABASE_URL.removeprefix("sqlite+aiosqlite:///./")).as_posix()

IS_SQLITE = DATABASE_URL.startswith("sqlite")

# SQLite allows one writer at a time, but with WAL (below) readers never wait for it. A single pooled connection
# used to make every request queue behind whichever one was waiting on Yahoo, so keep a few connections around;
# writers that collide wait up to busy_timeout instead of failing.
engine = create_async_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30} if IS_SQLITE else {},
    pool_size=8,
    max_overflow=4,
    pool_timeout=30,
)

if IS_SQLITE:
    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")  # readers and the writer stop blocking each other
        cursor.execute("PRAGMA busy_timeout=10000")  # wait up to 10 s for the write lock instead of erroring
        cursor.execute("PRAGMA synchronous=NORMAL")  # the safe, faster setting for WAL
        cursor.close()

async_session_maker = async_sessionmaker(engine, expire_on_commit=False)

# Columns added to existing tables after the first release. create_all only creates missing tables, so on startup
# each missing column here is added with ALTER TABLE. Entries: table -> [(column, SQL type + default, backfill SQL)].
# Keep the models and this list in step.
ADDED_COLUMNS = {
    # the price and currency a trade was typed in (nullable: older trades only have the CAD price)
    "transactions": [
        ("price_entered", "NUMERIC(20, 10)", None),
        ("currency_entered", "VARCHAR", None),
        # the CoinGecko id of a crypto trade (nullable: older trades only have the ticker)
        ("coin_id", "VARCHAR", None),
    ],
    "user": [
        # bumped to sign out every device (password reset/change, email change, "log out of all devices")
        ("token_version", "INTEGER NOT NULL DEFAULT 0", None),
        # False for accounts made with Google, whose password is random and unknown to the owner
        ("has_password", "BOOLEAN NOT NULL DEFAULT TRUE", None),
        # set once an email address has been confirmed; never-confirmed accounts are deleted after 7 days.
        # Existing accounts that are verified, or have transactions (only possible once verified), count as confirmed
        ("ever_verified", "BOOLEAN NOT NULL DEFAULT FALSE",
         'UPDATE "user" SET ever_verified = TRUE WHERE is_verified = TRUE '
         'OR id IN (SELECT user_id FROM transactions)'),
    ],
}


def _missing_columns(sync_conn):
    inspector = inspect(sync_conn)
    missing = []
    for table, columns in ADDED_COLUMNS.items():
        if not inspector.has_table(table):
            continue
        existing = {column["name"] for column in inspector.get_columns(table)}
        missing += [(table, *column) for column in columns if column[0] not in existing]
    return missing


def _add_missing_columns(sync_conn) -> None:
    for table, column, definition, backfill in _missing_columns(sync_conn):
        sync_conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {column} {definition}'))
        if backfill:
            sync_conn.execute(text(backfill))


async def add_missing_columns(conn) -> None:
    await conn.run_sync(_add_missing_columns)


async def create_db_and_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await add_missing_columns(conn)
        # Google tokens used to be saved with linked accounts but were never used again; blank any left over
        await conn.execute(update(OAuthAccount).where(OAuthAccount.access_token != "")
                           .values(access_token="", refresh_token=None, expires_at=None))


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


async def get_user_db(session: AsyncSession = Depends(get_async_session)):
    yield SQLAlchemyUserDatabase(session, User, OAuthAccount)
