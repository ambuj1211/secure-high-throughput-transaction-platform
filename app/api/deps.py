import logging
import time
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import User
from app.services.rate_limiter import RateLimiter

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login",
)

logger = logging.getLogger(__name__)

_PERF_SAMPLE_EVERY = 50
_auth_counter = 0

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


DBSession = Annotated[Session, Depends(get_db)]
BearerToken = Annotated[str, Depends(oauth2_scheme)]



def get_current_user_id(
    token: BearerToken,
) -> UUID:
    global _auth_counter

    _auth_counter += 1
    perf_sample = _auth_counter % _PERF_SAMPLE_EVERY == 0

    start = time.perf_counter()

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )

        user_id = payload.get("sub")

        if not user_id:
            raise credentials_exception

        result = UUID(str(user_id))

        if perf_sample:
            auth_ms = (time.perf_counter() - start) * 1000
            logger.warning(
                "AUTH_PERF total=%.2fms",
                auth_ms,
            )

        return result

    except (
        jwt.ExpiredSignatureError,
        jwt.InvalidTokenError,
        ValueError,
    ) as exc:
        raise credentials_exception from exc

CurrentUserId = Annotated[UUID, Depends(get_current_user_id)]

def get_current_user(
    token: BearerToken,
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )

        user_id = payload.get("sub")

        if not user_id:
            raise credentials_exception

    except jwt.ExpiredSignatureError as exc:
        raise credentials_exception from exc
    except jwt.InvalidTokenError as exc:
        raise credentials_exception from exc

    # Authentication uses its own short-lived session.
    # This keeps the business transaction session independent.
    with SessionLocal() as auth_db:
        user = auth_db.get(User, user_id)

        if user is None:
            raise credentials_exception

        # User attributes are already loaded. Closing auth_db
        # detaches the object without starting another transaction.
        return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> User:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )

    return user


CurrentAdmin = Annotated[User, Depends(require_admin)]


def enforce_login_rate_limit(request: Request):
    client_host = request.client.host if request.client is not None else "unknown"

    limiter = RateLimiter(settings.redis_url)

    allowed, _ = limiter.check(
        key=f"rate-limit:login:{client_host}",
        limit=settings.login_rate_limit_requests,
        window_seconds=settings.login_rate_limit_window_seconds,
    )

    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again later.",
            headers={"Retry-After": str(settings.login_rate_limit_window_seconds)},
        )
