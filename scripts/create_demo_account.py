"""
Create (or reset) the App Review demo account: a verified user with a few months of stock and crypto trades, so the
dashboard, holdings and charts aren't empty when Apple's reviewer signs in.

Run it on the server from the project root, after the backend has started once (so the tables exist):

    .venv/bin/python scripts/create_demo_account.py appreview@zenithwalletracker.ca
    .venv/bin/python scripts/create_demo_account.py appreview@zenithwalletracker.ca --reset

The password is asked for (or read from DEMO_PASSWORD) and must pass the normal password rules. --reset puts an
existing demo account back to a known state: same password, verified, signed out everywhere, sample trades only. Run it
again before every resubmission, since a reviewer may delete the account, change its password or log out everywhere.
"""
import argparse
import asyncio
import getpass
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi_users import exceptions  # noqa: E402
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase  # noqa: E402
from sqlalchemy import delete, func, select  # noqa: E402

from backend.db.database import async_session_maker  # noqa: E402
from backend.db_models.assets import OAuthAccount, Transaction, User, UserManager  # noqa: E402
from backend.services.asset_services import rebuild_symbol_ledger  # noqa: E402

class DemoAccountError(Exception):
    pass


# (days ago, action, asset_type, symbol, coin_id, quantity, price in CAD). Rough real prices, so the returns look
# plausible; the app prices the holdings live, these only set the cost basis.
SAMPLE_TRADES = [
    (270, "BUY", "stock", "AAPL", None, 10, 265.00),
    (240, "BUY", "stock", "MSFT", None, 5, 560.00),
    (220, "BUY", "crypto", "btc", "bitcoin", 0.05, 128000.00),
    (200, "BUY", "stock", "SHOP.TO", None, 15, 150.00),
    (160, "BUY", "crypto", "eth", "ethereum", 1.2, 4300.00),
    (120, "BUY", "stock", "AAPL", None, 5, 290.00),
    (90, "SELL", "stock", "SHOP.TO", None, 5, 175.00),
    (60, "BUY", "crypto", "sol", "solana", 10, 240.00),
    (30, "SELL", "crypto", "eth", "ethereum", 0.4, 4700.00),
    (14, "BUY", "stock", "XEQT.TO", None, 40, 36.50),
]


async def create_demo_account(email: str, password: str, reset: bool = False, name: str = "App Review") -> int:
    """Create or reset the demo user and return how many sample trades it now has."""
    async with async_session_maker() as session:
        user_db = SQLAlchemyUserDatabase(session, User, OAuthAccount)
        manager = UserManager(user_db)
        existing = await user_db.get_by_email(email)
        if existing is not None and not reset:
            raise DemoAccountError(f"{email} already exists; run again with --reset to put it back to the demo state.")

        await manager.validate_password(password, existing or User(email=email))
        hashed = manager.password_helper.hash(password)

        if existing is None:
            user = User(email=email, hashed_password=hashed, name=name, currency="CAD", is_active=True,
                        is_verified=True, ever_verified=True, has_password=True)
            session.add(user)
            await session.flush()
        else:
            user = existing
            await session.execute(delete(Transaction).where(Transaction.user_id == user.id))
            await session.execute(delete(OAuthAccount).where(OAuthAccount.user_id == user.id))
            user.hashed_password = hashed
            user.is_active = True
            user.is_verified = True
            user.ever_verified = True
            user.has_password = True
            user.currency = "CAD"
            # a reviewer may have signed in elsewhere or used "log out of all devices"; start from a clean slate
            user.token_version = (user.token_version or 0) + 1

        now = datetime.now(timezone.utc).replace(tzinfo=None)  # stored as naive UTC
        for days_ago, action, asset_type, symbol, coin_id, quantity, price in SAMPLE_TRADES:
            session.add(Transaction(
                user_id=user.id, action=action, profit=0, asset_type=asset_type, symbol=symbol, api_id=symbol,
                coin_id=coin_id, price_of_one=price, price_entered=price, currency_entered="CAD",
                quantity=quantity, created_at=now - timedelta(days=days_ago),
            ))
        await session.flush()

        # the same replay the API runs, so sells get their profit and the history is known to be valid
        for symbol in {t[3] for t in SAMPLE_TRADES}:
            if not await rebuild_symbol_ledger(session, user.id, symbol):
                await session.rollback()
                raise DemoAccountError(f"Sample trades for {symbol} sell more than they buy; fix SAMPLE_TRADES.")

        await session.commit()
        count = await session.scalar(select(func.count()).select_from(Transaction)
                                     .where(Transaction.user_id == user.id))
        return int(count)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or reset the App Review demo account.")
    parser.add_argument("email")
    parser.add_argument("--reset", action="store_true", help="reset an existing demo account")
    args = parser.parse_args()

    password = os.getenv("DEMO_PASSWORD") or getpass.getpass("Demo account password: ")
    try:
        count = asyncio.run(create_demo_account(args.email.strip().lower(), password, reset=args.reset))
    except exceptions.InvalidPasswordException as error:
        raise SystemExit(f"Password rejected: {error.reason}")
    except DemoAccountError as error:
        raise SystemExit(str(error))
    print(f"Demo account {args.email} is ready: verified, {count} sample trades. "
          "Put the email and password in App Store Connect -> App Review Information.")


if __name__ == "__main__":
    main()
