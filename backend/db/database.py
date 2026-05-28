from collections.abc import AsyncGenerator

from fastapi import Depends
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from backend.db_models.assets import Base, User

DATABASE_URL = "sqlite+aiosqlite:///./walletdatabase.db"

engine = create_async_engine(    DATABASE_URL,
    connect_args={"check_same_thread": False},  # required for SQLite
    pool_size=1,         # SQLite only supports 1 real writer at a time
    max_overflow=0,
    pool_timeout=60,
)

async_session_maker = async_sessionmaker(engine, expire_on_commit=False)

async def create_db_and_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session

async def get_user_db(session: AsyncSession = Depends(get_async_session)):
     yield SQLAlchemyUserDatabase(session, User)
