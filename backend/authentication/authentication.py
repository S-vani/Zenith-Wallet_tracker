import uuid

import jwt
from fastapi import Depends, Request
from fastapi_users import FastAPIUsers, exceptions
from fastapi_users.authentication import AuthenticationBackend, BearerTransport, JWTStrategy
from fastapi_users.jwt import decode_jwt, generate_jwt
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from backend.db.database import get_user_db
from backend.db_models.assets import UserManager, User

from dotenv import load_dotenv
import os

load_dotenv()

# The website keeps the usual one-hour token. The iPhone app asks for a long one (header below) so people aren't
# signed out every hour; that's acceptable because every token can be revoked through token_version.
WEB_TOKEN_LIFETIME = 60 * 60
APP_TOKEN_LIFETIME = 30 * 24 * 60 * 60
APP_CLIENT_HEADER = "x-zenith-client"
APP_CLIENT_VALUE = "ios-app"


async def get_user_manager(user_db: SQLAlchemyUserDatabase = Depends(get_user_db)):
    yield UserManager(user_db)


bearer_transport = BearerTransport(tokenUrl="auth/jwt/login")


class VersionedJWTStrategy(JWTStrategy):
    """
    A normal fastapi-users JWT plus the user's token_version ("ver"). A token whose version no longer matches the
    user's is rejected, so bumping token_version signs out every device at once (password reset or change, email
    change, "Log out of all devices"). Tokens from before this existed have no "ver" and count as version 0.
    """

    def __init__(self, *args, app: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.app = app

    async def write_token(self, user: User) -> str:
        data = {"sub": str(user.id), "aud": self.token_audience, "ver": int(user.token_version or 0)}
        if self.app:
            data["app"] = True  # an iPhone app sign in: the only kind POST /user/token renews
        return generate_jwt(data, self.encode_key, self.lifetime_seconds, algorithm=self.algorithm)

    async def read_token(self, token: str | None, user_manager) -> User | None:
        if token is None:
            return None
        try:
            data = decode_jwt(token, self.decode_key, self.token_audience, algorithms=[self.algorithm])
            user = await user_manager.get(user_manager.parse_id(data.get("sub")))
        # TypeError / ValueError: a correctly signed token with a missing "sub" or a list as "exp" is still just an
        # invalid token (401), not a server error
        except (jwt.PyJWTError, exceptions.UserNotExists, exceptions.InvalidID, TypeError, ValueError):
            return None
        version = data.get("ver", 0)
        if not isinstance(version, int) or version != int(user.token_version or 0):
            return None
        return user


def is_app_request(request: Request | None) -> bool:
    return request is not None and request.headers.get(APP_CLIENT_HEADER, "").strip().lower() == APP_CLIENT_VALUE


def get_jwt_strategy(request: Request = None) -> VersionedJWTStrategy:
    app = is_app_request(request)
    return VersionedJWTStrategy(secret=os.getenv("SECRET"), lifetime_seconds=APP_TOKEN_LIFETIME if app else
                                WEB_TOKEN_LIFETIME, app=app)


def is_app_token(token: str | None) -> bool:
    """Whether an (already verified) login token came from an iPhone app sign in."""
    try:
        return bool(jwt.decode(token or "", options={"verify_signature": False}).get("app"))
    except jwt.PyJWTError:
        return False


auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy
)

fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])
current_active_user = fastapi_users.current_user(active=True, verified=True)
