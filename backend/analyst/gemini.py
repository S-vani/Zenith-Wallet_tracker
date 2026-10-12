"""
Optional: let Google Gemini (free tier) reword the rules engine's text so it reads more naturally.

Gemini never decides anything: the sentiment, numbers, scenarios and ranges all come from the rules engine. It only
gets the finished draft and the facts, and its rewrite is thrown away (keeping the rules wording) if it:
  - fails, times out, hits the free-tier limit, or returns something that isn't the expected JSON
  - changes the number of items, or exceeds length limits
  - mentions any number that isn't already in the draft or the metrics (i.e. it invented a figure)
  - contradicts the sentiment
Enabled only when GEMINI_API_KEY is set (get one free at https://aistudio.google.com).
"""
import json
import logging
import os
import re
from typing import Optional

import httpx

from backend.analyst.schema import AnalystReport

log = logging.getLogger("uvicorn.error")

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-2.5-flash"
TIMEOUT_SECONDS = 20

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")

PROMPT = """You are the writing editor for a stock and crypto research panel.
Rewrite the DRAFT below so it reads like a concise, professional market analyst note: clear, specific, neutral in tone.

Strict rules:
- Keep the meaning, the sentiment ({sentiment}) and the confidence ({confidence}) exactly as they are.
- Use ONLY the facts and numbers in DRAFT and FACTS. Do not add numbers, dates, prices, news, events, companies,
  analyst opinions or predictions that aren't there. Copy numbers exactly as written (same rounding and symbols).
- No buy/sell instructions and no hype. Don't mention that you are an AI or that this is a rewrite.
- Keep the same number of items in every list, in the same order.
- summary: 2-4 sentences. reasons: short phrases. insight titles: max 6 words; details: 1-2 sentences.
  scenario summaries: 1 sentence. risk detail: 1-2 sentences. bottom_line: 2 sentences.

FACTS (data the analysis is based on):
{facts}

DRAFT (JSON):
{draft}
"""


def _schema(n_reasons: int, n_insights: int) -> dict:
    text = {"type": "STRING"}
    return {
        "type": "OBJECT",
        "properties": {
            "summary": text,
            "reasons": {"type": "ARRAY", "items": text, "minItems": n_reasons, "maxItems": n_reasons},
            "insights": {"type": "ARRAY", "minItems": n_insights, "maxItems": n_insights, "items": {
                "type": "OBJECT", "properties": {"title": text, "detail": text}, "required": ["title", "detail"]}},
            "scenario_summaries": {"type": "ARRAY", "items": text, "minItems": 3, "maxItems": 3},
            "risk_title": text,
            "risk_detail": text,
            "bottom_line": text,
        },
        "required": ["summary", "reasons", "insights", "scenario_summaries", "risk_title", "risk_detail",
                     "bottom_line"],
    }


def _numbers(text: str) -> set[str]:
    found = set()
    for match in _NUMBER.findall(text):
        value = match.replace(",", "")
        if "." in value:
            value = value.rstrip("0").rstrip(".")
        found.add(value)
    return found


def validate_rewrite(report: AnalystReport, rewrite: dict) -> Optional[str]:
    """Returns the reason the rewrite is rejected, or None if it's safe to use."""
    try:
        reasons, insights = rewrite["reasons"], rewrite["insights"]
        texts = [rewrite["summary"], *reasons, *[i["title"] for i in insights], *[i["detail"] for i in insights],
                 *rewrite["scenario_summaries"], rewrite["risk_title"], rewrite["risk_detail"],
                 rewrite["bottom_line"]]
    except (KeyError, TypeError):
        return "missing fields"

    if not all(isinstance(t, str) and t.strip() for t in texts):
        return "empty text"
    if len(reasons) != len(report.reasons) or len(insights) != len(report.insights) \
            or len(rewrite["scenario_summaries"]) != len(report.scenarios):
        return "item count changed"
    if len(rewrite["summary"]) > 700 or any(len(t) > 400 for t in texts[1:]):
        return "too long"

    allowed = set()
    draft_texts = [report.summary, *report.reasons, *[i.title for i in report.insights],
                   *[i.detail for i in report.insights], *[s.summary for s in report.scenarios],
                   report.bottom_line or ""]
    if report.main_risk:
        draft_texts += [report.main_risk.title, report.main_risk.detail]
    for text in draft_texts + [m.value for m in report.metrics] + [m.label for m in report.metrics]:
        allowed |= _numbers(text)
    invented = set().union(*(_numbers(t) for t in texts)) - allowed
    if invented:
        return f"new numbers {sorted(invented)}"

    opposite = {"bullish": "bearish", "bearish": "bullish"}.get(report.sentiment or "")
    if opposite and opposite in rewrite["summary"].lower():
        return "contradicts sentiment"
    return None


def apply_rewrite(report: AnalystReport, rewrite: dict) -> AnalystReport:
    updated = report.model_copy(deep=True)
    updated.summary = rewrite["summary"].strip()
    updated.reasons = [r.strip() for r in rewrite["reasons"]]
    for insight, new in zip(updated.insights, rewrite["insights"]):
        insight.title, insight.detail = new["title"].strip(), new["detail"].strip()
    for scenario, new in zip(updated.scenarios, rewrite["scenario_summaries"]):
        scenario.summary = new.strip()
    if updated.main_risk:
        updated.main_risk.title = rewrite["risk_title"].strip()
        updated.main_risk.detail = rewrite["risk_detail"].strip()
    updated.bottom_line = rewrite["bottom_line"].strip()
    updated.engine = "gemini"
    return updated


async def reword(report: AnalystReport) -> AnalystReport:
    """Gemini-reworded copy of the report, or the original if Gemini isn't configured or the rewrite isn't safe."""
    key = os.getenv("GEMINI_API_KEY")
    if not key or report.status != "ok" or not report.main_risk:
        return report

    draft = {
        "summary": report.summary,
        "reasons": report.reasons,
        "insights": [{"title": i.title, "detail": i.detail} for i in report.insights],
        "scenario_summaries": [s.summary for s in report.scenarios],
        "risk_title": report.main_risk.title,
        "risk_detail": report.main_risk.detail,
        "bottom_line": report.bottom_line,
    }
    facts = "\n".join(f"- {m.label}: {m.value}" for m in report.metrics)
    prompt = PROMPT.format(sentiment=report.sentiment, confidence=report.confidence, facts=facts,
                           draft=json.dumps(draft, ensure_ascii=False, indent=1))
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "responseMimeType": "application/json",
            "responseSchema": _schema(len(report.reasons), len(report.insights)),
        },
    }

    model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            res = await client.post(API_URL.format(model=model), json=body, headers={"x-goog-api-key": key})
        if res.status_code != 200:
            log.warning("Gemini rewording skipped: HTTP %s", res.status_code)  # e.g. 429 = free tier limit hit
            return report
        text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
        rewrite = json.loads(text)
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        log.warning("Gemini rewording skipped: %s", type(exc).__name__)
        return report

    problem = validate_rewrite(report, rewrite)
    if problem:
        log.info("Gemini rewording rejected (%s); using the rules engine wording", problem)
        return report
    return apply_rewrite(report, rewrite)
