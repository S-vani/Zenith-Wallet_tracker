"""
POST /transactions/scan: read the trades on a screenshot of a trade confirmation (Google Gemini) so the add-trade
form can be prefilled. Saves nothing; the user checks every field and saves the trade themselves. The reading and
the checks live in backend/services/scan.py.

The upload is parsed here instead of with FastAPI's File(): Starlette spools uploads over 1 MB to a temporary file
on disk, and a screenshot of someone's trades must only ever be in memory (see the privacy note in services/scan.py).
"""
import time
from collections import deque

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from backend.authentication.authentication import current_active_user
from backend.db.database import get_async_session
from backend.db_models.assets import User
from backend.routes.assets import _check_user_rate
from backend.services import scan
from backend.services.asset_services import end_read

router = APIRouter(tags=["scan"])

# Each scan is one Gemini call on the free tier, which allows only so many a day for the whole server
SCANS_PER_HOUR = 15  # per user
GLOBAL_SCANS_PER_HOUR = 200  # all users together, so a few busy accounts can't use up the key for everyone
SCAN_WINDOW = 3600  # seconds
USER_LIMIT_MESSAGE = "You've scanned a lot of screenshots in the last hour. Please wait a while and try again."
GLOBAL_LIMIT_MESSAGE = ("Screenshot import is very busy right now. Please try again in a few minutes, or add the "
                        "trade by hand.")
_scan_times: dict = {}  # {user id: deque of the times of their recent scans}
_global_scan_times: deque = deque()  # times of every scan in the last hour, all users together

# The image plus the multipart boundaries and part headers; anything bigger is refused before it's all read
MAX_BODY_BYTES = scan.MAX_IMAGE_BYTES + 64 * 1024


class _InMemoryMultiPartParser(MultiPartParser):
    """Starlette's multipart parser with a spool size above the body limit, so the upload never goes to disk."""
    spool_max_size = MAX_BODY_BYTES + 1


async def _read_body(request: Request) -> bytes:
    """The raw request body, or a 413 as soon as it's bigger than MAX_BODY_BYTES (checked while reading too, since
    Content-Length can be missing or wrong)."""
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail=scan.TOO_LARGE)
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail=scan.TOO_LARGE)
    return bytes(body)


async def _read_image(request: Request) -> tuple[bytes, str]:
    """(image bytes, real type) from the multipart field "image": 413 when too large, 415 when it isn't a PNG,
    JPEG, WebP or HEIC / HEIF image (by its bytes, whatever type was declared), 422 when it's missing or empty."""
    if not request.headers.get("content-type", "").lower().startswith("multipart/form-data"):
        raise HTTPException(status_code=422, detail=scan.EMPTY)
    body = await _read_body(request)

    async def chunks():
        """The body for the parser (it reads from an async stream)."""
        yield body

    parser = _InMemoryMultiPartParser(request.headers, chunks(), max_files=1, max_fields=5, max_part_size=1024)
    try:
        form = await parser.parse()
    except MultiPartException:
        raise HTTPException(status_code=422, detail=scan.EMPTY)
    try:
        upload = form.get("image")
        if not isinstance(upload, UploadFile):
            raise HTTPException(status_code=422, detail=scan.EMPTY)
        data = await upload.read()
    finally:
        await form.close()
    if not data:
        raise HTTPException(status_code=422, detail=scan.EMPTY)
    if len(data) > scan.MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail=scan.TOO_LARGE)
    mime_type = scan.image_type(data)
    if mime_type is None:
        raise HTTPException(status_code=415, detail=scan.WRONG_TYPE)
    return data, mime_type


def _take_scan_slot(user_id) -> None:
    """Count one scan for the user and for everyone, or raise a 429 with Retry-After (nothing is counted then)."""
    now = time.monotonic()
    while _global_scan_times and now - _global_scan_times[0] >= SCAN_WINDOW:
        _global_scan_times.popleft()
    if len(_global_scan_times) >= GLOBAL_SCANS_PER_HOUR:
        retry = max(1, int(SCAN_WINDOW - (now - _global_scan_times[0])) + 1)  # when the oldest one expires
        raise HTTPException(status_code=429, detail=GLOBAL_LIMIT_MESSAGE, headers={"Retry-After": str(retry)})
    _check_user_rate(_scan_times, user_id, SCANS_PER_HOUR, SCAN_WINDOW, USER_LIMIT_MESSAGE)
    _global_scan_times.append(now)


def _refund_scan_slot(user_id) -> None:
    """Give back the slots of a scan Gemini failed on, so its errors don't use up the hourly limits."""
    times = _scan_times.get(user_id)
    if times:
        times.pop()
    if _global_scan_times:
        _global_scan_times.pop()


@router.post("/transactions/scan")
async def scan_screenshot(
        request: Request,
        session: AsyncSession = Depends(get_async_session),
        current_user: User = Depends(current_active_user),
):
    """
    Read the buys and sells on a screenshot (multipart field "image": PNG, JPEG, WebP or HEIC, at most 2.5 MB) and
    return them checked like an imported CSV row, for the user to review: {"trades": [...], "warnings": [...]}.
    A field that can't be read or fails a check is null with a note. Never saves anything, and the image is only
    kept in memory for this request.
    503 without a Gemini key, 413 / 415 / 422 for the upload, 429 past SCANS_PER_HOUR per user or
    GLOBAL_SCANS_PER_HOUR in total, 502 when Gemini fails (not counted) and 422 when no trade was found.
    """
    if not scan.scan_enabled():
        raise HTTPException(status_code=503, detail=scan.UNAVAILABLE)
    await end_read(session)  # the user is loaded; don't hold a database connection while the upload and Gemini run
    image, mime_type = await _read_image(request)
    _take_scan_slot(current_user.id)
    try:
        answer = await scan.read_screenshot(image, mime_type)
    except scan.ScanUnavailable:
        _refund_scan_slot(current_user.id)
        raise HTTPException(status_code=503, detail=scan.UNAVAILABLE)
    except scan.ScanFailed:
        _refund_scan_slot(current_user.id)
        raise HTTPException(status_code=502, detail=scan.READ_FAILED)
    try:
        return await scan.build_scan_result(answer, current_user.currency)
    except scan.NoTradesFound:
        raise HTTPException(status_code=422, detail=scan.NO_TRADES)
