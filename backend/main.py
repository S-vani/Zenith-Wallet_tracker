import uvicorn
import os
import sys
from pathlib import Path

# The code imports "backend.xxx", so the project root has to be importable even when this file is run directly
# (e.g. "python main.py" from inside the backend folder or the PyCharm run button)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI
from backend.schemas.assets import UserCreate, UserRead, UserUpdate
from backend.db.database import create_db_and_tables
from contextlib import asynccontextmanager
from backend.authentication.authentication import auth_backend, fastapi_users
from backend.routes.assets import router as user_router
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_db_and_tables()
    yield


app = FastAPI(lifespan=lifespan)


frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")


class CatchUnhandledErrors(BaseHTTPMiddleware):
    """
    Turn unexpected crashes into a normal JSON 500. Without this the error response skips the CORS middleware,
    so the browser hides it and the frontend can only report "can't reach the server".
    """

    async def dispatch(self, request, call_next):
        try:
            return await call_next(request)
        except Exception:
            logging.getLogger("uvicorn.error").exception("Unhandled error on %s %s", request.method, request.url.path)
            return JSONResponse(status_code=500, content={"detail": "Something went wrong on our end. Please try again."})


# added before CORS so it sits inside it, and its 500 responses still get CORS headers
app.add_middleware(CatchUnhandledErrors)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(fastapi_users.get_auth_router(auth_backend, requires_verification=True),prefix="/auth/jwt", tags=["auth"])
app.include_router(fastapi_users.get_register_router(UserRead, UserCreate), prefix="/auth", tags=["auth"])
app.include_router(fastapi_users.get_reset_password_router(), prefix="/auth", tags=["auth"])
app.include_router(fastapi_users.get_verify_router(UserRead), prefix="/auth", tags=["auth"])
app.include_router(fastapi_users.get_users_router(UserRead, UserUpdate), prefix="/users", tags=["users"])
app.include_router(user_router)

if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True,
                app_dir=str(PROJECT_ROOT), reload_dirs=[str(PROJECT_ROOT / "backend")])
