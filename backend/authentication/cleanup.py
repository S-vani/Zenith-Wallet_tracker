"""
Deleting accounts: the user's own "Delete account" and the sweep of sign-ups that were never verified.

An unverified account can't log in, so its owner could never delete it themselves. Accounts that haven't confirmed
their email within UNVERIFIED_GRACE are therefore removed, together with anything attached to them. The privacy
policy says so. Accounts that were verified once and are only unverified because the email was changed are kept
(ever_verified).
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.analyst.service import forget_user
from backend.db.database import async_session_maker
from backend.db_models.assets import OAuthAccount, Transaction, User

UNVERIFIED_GRACE = timedelta(days=7)
SWEEP_EVERY_SECONDS = 6 * 60 * 60


async def delete_users(session: AsyncSession, user_ids: list) -> None:
    """Delete these users with their transactions and linked Google sign-ins, in the session's transaction."""
    if not user_ids:
        return
    # bulk deletes, so the ORM doesn't try to null out the foreign keys of the user's children first
    await session.execute(delete(Transaction).where(Transaction.user_id.in_(user_ids)))
    await session.execute(delete(OAuthAccount).where(OAuthAccount.user_id.in_(user_ids)))
    await session.execute(delete(User).where(User.id.in_(user_ids)))
    await session.commit()
    for user_id in user_ids:
        forget_user(str(user_id))  # the analyst's in-memory rate limit


async def delete_stale_unverified_users(now: datetime | None = None) -> int:
    """Remove accounts that never confirmed their email and are older than UNVERIFIED_GRACE. Returns how many."""
    # date_joined is stored as naive UTC
    cutoff = ((now or datetime.now(timezone.utc)) - UNVERIFIED_GRACE).astimezone(timezone.utc).replace(tzinfo=None)
    async with async_session_maker() as session:
        result = await session.execute(
            select(User.id).where(User.is_verified.is_(False), User.ever_verified.is_(False),
                                  User.date_joined < cutoff)
        )
        stale = list(result.scalars().all())
        await delete_users(session, stale)
    if stale:
        logging.getLogger("uvicorn.error").info("Deleted %d unverified account(s) older than 7 days", len(stale))
    return len(stale)


async def sweep_unverified_forever() -> None:
    """Runs for the life of the server (started in main.py's lifespan): a sweep at startup, then every 6 hours."""
    while True:
        try:
            await delete_stale_unverified_users()
        except Exception:
            logging.getLogger("uvicorn.error").exception("Couldn't delete stale unverified accounts")
        await asyncio.sleep(SWEEP_EVERY_SECONDS)
