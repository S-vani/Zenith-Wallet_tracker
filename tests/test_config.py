"""GET /config: the effects kill switch the website and the app read at startup."""
import pytest


@pytest.mark.parametrize("setting, expected", [
    (None, "full"), ("", "full"), ("full", "full"), ("lite", "lite"), ("OFF", "off"), (" Lite ", "lite"),
    ("nonsense", "full"),
])
def test_fx_level(client, monkeypatch, setting, expected):
    if setting is None:
        monkeypatch.delenv("FX_LEVEL", raising=False)
    else:
        monkeypatch.setenv("FX_LEVEL", setting)
    res = client.get("/config")
    assert res.status_code == 200
    assert res.json() == {"fx_level": expected}


def test_config_is_public_and_cacheable(client):
    res = client.get("/config")  # no login
    assert res.status_code == 200 and "max-age=300" in res.headers["cache-control"]
