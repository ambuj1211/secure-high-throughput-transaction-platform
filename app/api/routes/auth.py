from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import (
    CurrentAdmin,
    CurrentUser,
    DBSession,
    enforce_login_rate_limit,
)
from app.core.security import create_access_token, hash_password, verify_password
from app.models import Account, User
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(
    prefix="/api/v1/auth",
    tags=["auth"],
)


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(request: RegisterRequest, db: DBSession):
    email = request.email.strip().lower()

    existing_user = db.scalar(select(User).where(User.email == email))

    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = User(
        name=request.name.strip(),
        email=email,
        password_hash=hash_password(request.password),
        role="user",
    )

    db.add(user)

    # Assign the generated user ID before creating the account.
    db.flush()

    account = Account(
        user_id=user.id,
        balance=Decimal("0.00"),
        currency="INR",
    )

    db.add(account)

    # User and account are committed atomically.
    db.commit()
    db.refresh(user)

    return UserResponse(
        id=str(user.id),
        name=user.name,
        email=user.email,
        role=user.role,
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(enforce_login_rate_limit)],
)
def login(request: LoginRequest, db: DBSession):
    email = request.email.strip().lower()

    user = db.scalar(select(User).where(User.email == email))

    if user is None or user.password_hash is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(
        user_id=str(user.id),
        role=user.role,
    )

    return TokenResponse(access_token=token)


@router.get(
    "/me",
    response_model=UserResponse,
)
def get_me(user: CurrentUser):
    return UserResponse(
        id=str(user.id),
        name=user.name,
        email=user.email,
        role=user.role,
    )


@router.get("/admin-check")
def admin_check(user: CurrentAdmin):
    return {
        "message": "Admin access granted",
        "user_id": str(user.id),
    }
