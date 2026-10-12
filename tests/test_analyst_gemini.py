"""
Market Analyst: the optional Gemini rewording (backend/analyst/gemini.py). The HTTP client is always faked.
"""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from backend.analyst import gemini
from backend.analyst.engine import build_report
from backend.analyst.gemini import validate_rewrite
from tests.analyst_helpers import BAD_FUNDAMENTALS, GOOD_FUNDAMENTALS, make_data

_json = json  # `json` is shadowed by the keyword argument of the fake post()


@pytest.fixture(autouse=True)
def no_gemini_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)


@pytest.fixture(scope="module")
def bullish():
    return build_report(make_data("up", fundamentals=dict(GOOD_FUNDAMENTALS)))


@pytest.fixture(scope="module")
def bearish():
    return build_report(make_data("down", fundamentals=dict(BAD_FUNDAMENTALS)))


def draft_of(report):
    return {
        "summary": report.summary,
        "reasons": list(report.reasons),
        "insights": [{"title": i.title, "detail": i.detail} for i in report.insights],
        "scenario_summaries": [s.summary for s in report.scenarios],
        "risk_title": report.main_risk.title,
        "risk_detail": report.main_risk.detail,
        "bottom_line": report.bottom_line,
    }


def faithful(draft):
    """A rewrite that only changes wording (no new numbers, same item counts)."""
    return {
        "summary": "Analyst note: " + draft["summary"],
        "reasons": [r.lower() for r in draft["reasons"]],
        "insights": [{"title": i["title"] + " now", "detail": "In short, " + i["detail"]} for i in draft["insights"]],
        "scenario_summaries": ["Scenario: " + s for s in draft["scenario_summaries"]],
        "risk_title": draft["risk_title"] + " (key risk)",
        "risk_detail": "Mainly, " + draft["risk_detail"],
        "bottom_line": "Bottom line: " + draft["bottom_line"],
    }


# --------------------------------------------------------------------------- validate_rewrite
def test_faithful_rewrite_is_accepted(bullish, bearish):
    assert validate_rewrite(bullish, faithful(draft_of(bullish))) is None
    assert validate_rewrite(bearish, faithful(draft_of(bearish))) is None


def test_numbers_may_be_reformatted_but_not_changed(bullish):
    rewrite = faithful(draft_of(bullish))
    rewrite["summary"] += " The 90-day return is 19.50 percent."  # same number, different formatting
    assert validate_rewrite(bullish, rewrite) is None


@pytest.mark.parametrize("field", ["summary", "bottom_line", "risk_detail"])
def test_invented_numbers_are_rejected(bullish, field):
    rewrite = faithful(draft_of(bullish))
    rewrite[field] += " It could climb another 42.7% by March 2031."
    problem = validate_rewrite(bullish, rewrite)
    assert problem and problem.startswith("new numbers")
    assert "42.7" in problem and "2031" in problem


def test_invented_number_in_an_insight_is_rejected(bullish):
    rewrite = faithful(draft_of(bullish))
    rewrite["insights"][0]["detail"] = "Revenue doubled to 987 billion."
    assert validate_rewrite(bullish, rewrite).startswith("new numbers")


@pytest.mark.parametrize("change", ["drop_reason", "add_reason", "drop_insight", "two_scenarios"])
def test_changed_item_counts_are_rejected(bullish, change):
    rewrite = faithful(draft_of(bullish))
    if change == "drop_reason":
        rewrite["reasons"].pop()
    elif change == "add_reason":
        rewrite["reasons"].append("Another reason")
    elif change == "drop_insight":
        rewrite["insights"].pop()
    else:
        rewrite["scenario_summaries"].pop()
    assert validate_rewrite(bullish, rewrite) == "item count changed"


def test_overly_long_text_is_rejected(bullish):
    rewrite = faithful(draft_of(bullish))
    rewrite["summary"] = "Long words. " * 60  # > 700 characters
    assert validate_rewrite(bullish, rewrite) == "too long"

    rewrite = faithful(draft_of(bullish))
    rewrite["reasons"][0] = "word " * 81  # > 400 characters
    assert validate_rewrite(bullish, rewrite) == "too long"


def test_contradicting_the_sentiment_is_rejected(bullish, bearish):
    rewrite = faithful(draft_of(bullish))
    rewrite["summary"] = "The setup looks Bearish overall."
    assert validate_rewrite(bullish, rewrite) == "contradicts sentiment"

    rewrite = faithful(draft_of(bearish))
    rewrite["summary"] = "Despite everything, this is bullish."
    assert validate_rewrite(bearish, rewrite) == "contradicts sentiment"


@pytest.mark.parametrize("breakage", ["no_bottom_line", "no_summary", "insight_without_detail", "list", "null",
                                      "string", "scenarios_null"])
def test_missing_fields_are_rejected(bullish, breakage):
    rewrite = faithful(draft_of(bullish))
    if breakage == "no_bottom_line":
        del rewrite["bottom_line"]
    elif breakage == "no_summary":
        del rewrite["summary"]
    elif breakage == "insight_without_detail":
        del rewrite["insights"][0]["detail"]
    elif breakage == "list":
        rewrite = [rewrite]
    elif breakage == "null":
        rewrite = None
    elif breakage == "string":
        rewrite = "summary"
    else:
        rewrite["scenario_summaries"] = None
    assert validate_rewrite(bullish, rewrite) == "missing fields"


@pytest.mark.parametrize("value", ["", "   ", 42, None])
def test_empty_or_non_text_values_are_rejected(bullish, value):
    rewrite = faithful(draft_of(bullish))
    rewrite["risk_title"] = value
    assert validate_rewrite(bullish, rewrite) == "empty text"


# --------------------------------------------------------------------------- reword() with a fake HTTP client
class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def gemini_body(text):
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


@pytest.fixture
def fake_gemini(monkeypatch):
    """
    Replaces httpx inside backend.analyst.gemini. By default it answers with a faithful rewrite of the draft it was
    sent; set `.status`, `.body` (dict, or an Exception raised by .json()) or `.error` (raised by post) to change that.
    """
    state = SimpleNamespace(status=200, body=None, error=None, requests=[], client_kwargs=None)

    class AsyncClient:
        def __init__(self, *args, **kwargs):
            state.client_kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, headers=None, **kwargs):
            state.requests.append(SimpleNamespace(url=url, json=json, headers=headers or {}))
            if state.error:
                raise state.error
            body = state.body
            if body is None:
                prompt = json["contents"][0]["parts"][0]["text"]
                draft = _json.loads(prompt.split("DRAFT (JSON):\n", 1)[1])
                body = gemini_body(_json.dumps(faithful(draft)))
            return FakeResponse(state.status, body)

    monkeypatch.setattr(gemini, "httpx", SimpleNamespace(AsyncClient=AsyncClient, HTTPError=httpx.HTTPError))
    return state


def reword(report):
    return asyncio.run(gemini.reword(report))


def test_no_key_returns_the_original_without_any_request(bullish, fake_gemini):
    assert reword(bullish) is bullish
    assert fake_gemini.requests == []


def test_blank_key_counts_as_no_key(bullish, fake_gemini, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    assert reword(bullish) is bullish
    assert fake_gemini.requests == []


def test_valid_response_is_applied(bullish, fake_gemini, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
    result = reword(bullish)
    assert result.engine == "gemini"
    assert result.summary == "Analyst note: " + bullish.summary
    assert result.bottom_line == "Bottom line: " + bullish.bottom_line
    assert result.main_risk.title == bullish.main_risk.title + " (key risk)"
    assert [s.summary for s in result.scenarios] == ["Scenario: " + s.summary for s in bullish.scenarios]
    assert [i.detail for i in result.insights] == ["In short, " + i.detail for i in bullish.insights]
    # the facts never change
    assert result.sentiment == bullish.sentiment and result.confidence == bullish.confidence
    assert result.score == bullish.score and result.metrics == bullish.metrics
    assert [s.ranges for s in result.scenarios] == [s.ranges for s in bullish.scenarios]
    # the original report object is untouched
    assert bullish.engine == "rules" and not bullish.summary.startswith("Analyst note")


def test_request_shape(bullish, fake_gemini, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
    reword(bullish)
    (req,) = fake_gemini.requests
    assert req.url == gemini.API_URL.format(model=gemini.DEFAULT_MODEL)
    assert req.headers == {"x-goog-api-key": "fake-gemini-key"}
    assert "fake-gemini-key" not in req.url  # the key goes in a header, never in the url
    schema = req.json["generationConfig"]["responseSchema"]["properties"]
    assert schema["reasons"]["minItems"] == schema["reasons"]["maxItems"] == len(bullish.reasons)
    assert schema["insights"]["maxItems"] == len(bullish.insights)
    assert fake_gemini.client_kwargs.get("timeout") == gemini.TIMEOUT_SECONDS


def test_model_can_be_overridden(bullish, fake_gemini, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test-model")
    reword(bullish)
    assert "models/gemini-test-model:generateContent" in fake_gemini.requests[0].url


@pytest.mark.parametrize("status", [429, 500, 503, 400])
def test_http_errors_fall_back_to_the_original(bullish, fake_gemini, monkeypatch, status):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
    fake_gemini.status = status
    fake_gemini.body = {"error": {"message": "quota"}}
    assert reword(bullish) is bullish


@pytest.mark.parametrize("body", [
    ValueError("not json"),  # the response body itself isn't JSON
    {"candidates": []},
    {"unexpected": True},
    gemini_body("Sure! Here is the rewrite you asked for."),  # text isn't JSON
    gemini_body("[1, 2, 3]"),
    gemini_body(None),
], ids=["body-not-json", "no-candidates", "wrong-shape", "text-not-json", "json-list", "null-text"])
def test_malformed_responses_fall_back_to_the_original(bullish, fake_gemini, monkeypatch, body):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
    fake_gemini.body = body
    assert reword(bullish) is bullish


@pytest.mark.parametrize("error", [httpx.ReadTimeout("timed out"), httpx.ConnectError("no route"),
                                   httpx.ConnectTimeout("slow")])
def test_timeouts_and_connection_errors_fall_back_to_the_original(bullish, fake_gemini, monkeypatch, error):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
    fake_gemini.error = error
    assert reword(bullish) is bullish


def test_unsafe_rewrite_falls_back_to_the_original(bullish, fake_gemini, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
    rewrite = faithful(draft_of(bullish))
    rewrite["summary"] = "Expect a 55% rally; this is bearish for shorts."
    fake_gemini.body = gemini_body(json.dumps(rewrite))
    result = reword(bullish)
    assert result is bullish
    assert result.engine == "rules"


def test_insufficient_data_reports_are_never_sent(fake_gemini, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
    report = build_report(make_data("up", n=10))
    assert reword(report) is report
    assert fake_gemini.requests == []
