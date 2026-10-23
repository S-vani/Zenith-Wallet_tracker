"""The App Review demo account script (scripts/create_demo_account.py)."""
import importlib.util

import pytest

from tests.conftest import PROJECT_ROOT, PASSWORD, login, unique_email

_spec = importlib.util.spec_from_file_location("create_demo_account",
                                               PROJECT_ROOT / "scripts" / "create_demo_account.py")
demo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(demo)


def test_demo_account_can_sign_in_and_has_valid_trades(client, run):
    email = unique_email("demo")
    count = run(demo.create_demo_account, email, PASSWORD)
    assert count == len(demo.SAMPLE_TRADES)

    res = login(client, email, PASSWORD)
    assert res.status_code == 200, res.text  # verified straight away, no email needed
    token = res.json()["access_token"]
    trades = client.get("/transactions", headers={"Authorization": f"Bearer {token}"})
    assert trades.status_code == 200, trades.text


def test_existing_account_needs_reset_and_reset_signs_out_old_tokens(client, run, db):
    email = unique_email("demo")
    run(demo.create_demo_account, email, PASSWORD)
    old_token = login(client, email, PASSWORD).json()["access_token"]

    with pytest.raises(demo.DemoAccountError):
        run(demo.create_demo_account, email, PASSWORD)

    db.set_user(email, is_verified=False)  # e.g. a reviewer changed the email
    assert run(lambda: demo.create_demo_account(email, PASSWORD, True)) == len(demo.SAMPLE_TRADES)
    assert db.get_user(email).is_verified
    assert client.get("/user", headers={"Authorization": f"Bearer {old_token}"}).status_code == 401
