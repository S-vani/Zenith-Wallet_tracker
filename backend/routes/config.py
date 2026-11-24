"""GET /config: the public settings the website and the app read at startup. Today just the effects kill switch."""
import os
from typing import Literal

from fastapi import APIRouter, Response

router = APIRouter(tags=["config"])

FX_LEVELS = ("full", "lite", "off")


def fx_level() -> Literal["full", "lite", "off"]:
    """
    FX_LEVEL from .env: "full" (default), "lite" (no heavy animations anywhere) or "off" (no animations). Changing it
    and restarting the API calms every device at once, without an App Store release. Anything else means "full".
    """
    value = (os.getenv("FX_LEVEL") or "full").strip().lower()
    return value if value in FX_LEVELS else "full"


@router.get("/config")
async def get_config(response: Response):
    """{"fx_level": "full" | "lite" | "off"}; cached for a few minutes by browsers and the app."""
    response.headers["Cache-Control"] = "public, max-age=300"
    return {"fx_level": fx_level()}
