"""DELETE /user: permanent in-app account deletion (required by the App Store and Google Play)."""
import uuid

from sqlalchemy import func, select

from backend.db.database import async_session_maker
from backend.db_models.assets import OAuthAccount, Transaction
from conftest import login, register


async def _link_google(user_id, email):
    async with async_session_maker() as session:
        session.add(OAuthAccount(oauth_name="google", access_token="test-token", account_id=f"g-{user_id}",
                                 account_email=email, user_id=uuid.UUID(user_id)))
        await session.commit()


async def _count(model, user_id):
    async with async_session_maker() as session:
        result = await session.execute(select(func.count()).select_from(model)
                                       .where(model.user_id == uuid.UUID(user_id)))
        return result.scalar_one()


def test_delete_account_removes_the_user_and_everything_they_own(client, user, db, buy, run):
    buy(user, "AAPL", 2, 100)
    buy(user, "btc", 0.1, 50000, asset_type="crypto")
    run(_link_google, user.id, user.email)

    res = client.delete("/user", headers=user.headers)
    assert res.status_code == 200
    assert res.json() == {"message": "Account deleted"}

    assert db.get_user(user.email) is None
    assert run(_count, Transaction, user.id) == 0
    assert run(_count, OAuthAccount, user.id) == 0


def test_deleted_account_can_no_longer_be_used(client, user):
    client.delete("/user", headers=user.headers)

    assert client.get("/user", headers=user.headers).status_code == 401  # the old token is dead
    assert login(client, user.email).status_code == 400  # and the password no longer works


def test_email_can_sign_up_again_after_deleting(client, user):
    client.delete("/user", headers=user.headers)
    assert register(client, email=user.email).status_code == 201


def test_deleting_one_account_leaves_other_users_alone(client, make_user, buy, run):
    leaving, staying = make_user(), make_user()
    buy(leaving, "AAPL", 1, 100)
    buy(staying, "AAPL", 3, 100)

    client.delete("/user", headers=leaving.headers)

    assert client.get("/user", headers=staying.headers).status_code == 200
    assert run(_count, Transaction, staying.id) == 1


def test_delete_account_requires_login(client):
    assert client.delete("/user").status_code == 401
