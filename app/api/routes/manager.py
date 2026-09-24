from decimal import Decimal
from typing import Literal, cast

from fastapi import APIRouter, Header, HTTPException, Query, Response, status
from redis import Redis
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import CurrentAdmin, DBSession
from app.core.config import settings
from app.core.security import hash_password
from app.models import Account, CashOperation, Merchant, Transaction, User
from app.schemas.auth import RegisterRequest
from app.schemas.manager import (
    CashOperationCreate,
    CashOperationResponse,
    ManagerAccountResponse,
    ManagerMerchantResponse,
    ManagerTransactionResponse,
    ManagerTransferCreate,
    ManagerUserResponse,
)
from app.schemas.transaction import TransactionCreate, TransactionType
from app.services.cash_service import perform_cash_operation
from app.services.exceptions import (
    AccountNotFoundError,
    IdempotencyConflictError,
    InsufficientFundsError,
)
from app.services.transaction_service import create_transaction

router = APIRouter(
    prefix="/api/v1/manager",
    tags=["Manager"],
)


# ---------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------


@router.post(
    "/users",
    response_model=ManagerUserResponse,
    status_code=status.HTTP_201_CREATED,
)
def manager_create_user(
    request: RegisterRequest,
    manager: CurrentAdmin,
    db: DBSession,
) -> ManagerUserResponse:
    email = request.email.strip().lower()

    existing = db.scalar(
        select(User).where(User.email == email),
    )

    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered.",
        )

    user = User(
        name=request.name.strip(),
        email=email,
        password_hash=hash_password(request.password),
        role="user",
    )

    db.add(user)
    db.flush()

    account = Account(
        user_id=user.id,
        balance=Decimal("0.00"),
        currency="INR",
    )

    db.add(account)
    db.commit()

    db.refresh(user)
    db.refresh(account)

    return ManagerUserResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        role=user.role,
        account_id=account.id,
        balance=account.balance,
        currency=account.currency,
    )


@router.get(
    "/users",
    response_model=list[ManagerUserResponse],
)
def manager_list_users(
    manager: CurrentAdmin,
    db: DBSession,
    limit: int = Query(default=500, ge=1, le=1000),
) -> list[ManagerUserResponse]:
    rows = db.execute(
        select(User, Account)
        .outerjoin(
            Account,
            Account.user_id == User.id,
        )
        .order_by(User.created_at.desc())
        .limit(limit),
    ).all()

    return [
        ManagerUserResponse(
            id=user.id,
            name=user.name,
            email=user.email,
            role=user.role,
            account_id=account.id if account else None,
            balance=account.balance if account else None,
            currency=account.currency if account else None,
        )
        for user, account in rows
    ]


# ---------------------------------------------------------------------
# Merchants
# ---------------------------------------------------------------------


@router.post(
    "/merchants",
    response_model=ManagerMerchantResponse,
    status_code=status.HTTP_201_CREATED,
)
def manager_create_merchant(
    request: ManagerMerchantResponse,
    manager: CurrentAdmin,
    db: DBSession,
) -> ManagerMerchantResponse:
    email = request.email.strip().lower()

    existing = db.scalar(
        select(Merchant).where(Merchant.email == email),
    )

    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Merchant email already registered.",
        )

    merchant = Merchant(
        name=request.name.strip(),
        email=email,
    )

    db.add(merchant)
    db.flush()

    account = Account(
        merchant_id=merchant.id,
        balance=Decimal("0.00"),
        currency="INR",
    )

    db.add(account)
    db.commit()

    db.refresh(merchant)
    db.refresh(account)

    return ManagerMerchantResponse(
        id=merchant.id,
        name=merchant.name,
        email=merchant.email,
        account_id=account.id,
        balance=account.balance,
        currency=account.currency,
    )


@router.get(
    "/merchants",
    response_model=list[ManagerMerchantResponse],
)
def manager_list_merchants(
    manager: CurrentAdmin,
    db: DBSession,
    limit: int = Query(default=500, ge=1, le=1000),
) -> list[ManagerMerchantResponse]:
    rows = db.execute(
        select(Merchant, Account)
        .outerjoin(
            Account,
            Account.merchant_id == Merchant.id,
        )
        .order_by(Merchant.created_at.desc())
        .limit(limit),
    ).all()

    return [
        ManagerMerchantResponse(
            id=merchant.id,
            name=merchant.name,
            email=merchant.email,
            account_id=account.id if account else None,
            balance=account.balance if account else None,
            currency=account.currency if account else None,
        )
        for merchant, account in rows
    ]


# ---------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------


@router.get(
    "/accounts",
    response_model=list[ManagerAccountResponse],
)
def manager_list_accounts(
    manager: CurrentAdmin,
    db: DBSession,
    limit: int = Query(default=500, ge=1, le=1000),
) -> list[ManagerAccountResponse]:
    rows = db.execute(
        select(Account, User, Merchant)
        .outerjoin(
            User,
            User.id == Account.user_id,
        )
        .outerjoin(
            Merchant,
            Merchant.id == Account.merchant_id,
        )
        .order_by(Account.updated_at.desc())
        .limit(limit),
    ).all()

    result: list[ManagerAccountResponse] = []

    for account, user, merchant in rows:
        if user is not None:
            owner_type: Literal["USER", "MERCHANT"] = "USER"
            owner_name = user.name
            owner_email = user.email
        elif merchant is not None:
            owner_type = "MERCHANT"
            owner_name = merchant.name
            owner_email = merchant.email
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Account {account.id} has no valid owner.",
            )

        result.append(
            ManagerAccountResponse(
                id=account.id,
                user_id=account.user_id,
                merchant_id=account.merchant_id,
                owner_type=owner_type,
                owner_name=owner_name,
                owner_email=owner_email,
                balance=account.balance,
                currency=account.currency,
                version=account.version,
                created_at=account.created_at,
                updated_at=account.updated_at,
            ),
        )

    return result


# ---------------------------------------------------------------------
# Cash operations
# ---------------------------------------------------------------------


@router.post(
    "/cash",
    response_model=CashOperationResponse,
)
def manager_cash_operation(
    request: CashOperationCreate,
    response: Response,
    manager: CurrentAdmin,
    db: DBSession,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
    ),
) -> CashOperationResponse:
    if not idempotency_key.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key must not be empty.",
        )

    try:
        operation, created = perform_cash_operation(
            db=db,
            manager_id=manager.id,
            request=request,
            idempotency_key=idempotency_key,
        )

        response.status_code = (
            status.HTTP_201_CREATED
            if created
            else status.HTTP_200_OK
        )

        return CashOperationResponse.model_validate(
            operation,
            from_attributes=True,
        )

    except AccountNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    except InsufficientFundsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    except IdempotencyConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/cash-operations",
    response_model=list[CashOperationResponse],
)
def manager_cash_operations(
    manager: CurrentAdmin,
    db: DBSession,
    limit: int = Query(default=500, ge=1, le=1000),
) -> list[CashOperationResponse]:
    operations = db.scalars(
        select(CashOperation)
        .order_by(CashOperation.created_at.desc())
        .limit(limit),
    ).all()

    return [
        CashOperationResponse.model_validate(
            operation,
            from_attributes=True,
        )
        for operation in operations
    ]


# ---------------------------------------------------------------------
# Transfers
# ---------------------------------------------------------------------


@router.post(
    "/transfers",
    response_model=ManagerTransactionResponse,
    status_code=status.HTTP_201_CREATED,
)
def manager_transfer(
    request: ManagerTransferCreate,
    manager: CurrentAdmin,
    db: DBSession,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
    ),
) -> ManagerTransactionResponse:
    if not idempotency_key.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key must not be empty.",
        )

    transaction_request = TransactionCreate(
        transaction_type=request.transaction_type,
        sender_account_id=request.sender_account_id,
        receiver_account_id=request.receiver_account_id,
        amount=request.amount,
        currency=request.currency,
        payment_token=request.payment_token,
    )

    try:
        transaction = create_transaction(
            db=db,
            user_id=manager.id,
            request=transaction_request,
            idempotency_key=idempotency_key,
            sender_account_id=request.sender_account_id,
        )

        return ManagerTransactionResponse(
            id=transaction.id,
            transaction_type=cast(
                TransactionType,
                transaction.transaction_type,
            ),
            sender_account_id=transaction.sender_account_id,
            receiver_account_id=transaction.receiver_account_id,
            amount=transaction.amount,
            currency=transaction.currency,
            status=transaction.status,
            idempotency_key=transaction.idempotency_key,
            risk_score=transaction.risk_score,
            risk_decision=transaction.risk_decision,
            risk_processed_at=transaction.risk_processed_at,
            created_at=transaction.created_at,
            updated_at=transaction.updated_at,
        )

    except AccountNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    except InsufficientFundsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    except IdempotencyConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get(
    "/transactions",
    response_model=list[ManagerTransactionResponse],
)
def manager_transactions(
    manager: CurrentAdmin,
    db: DBSession,
    limit: int = Query(default=500, ge=1, le=1000),
) -> list[ManagerTransactionResponse]:
    transactions = db.scalars(
        select(Transaction)
        .order_by(Transaction.created_at.desc())
        .limit(limit),
    ).all()

    return [
        ManagerTransactionResponse(
            id=transaction.id,
            transaction_type=cast(
                TransactionType,
                transaction.transaction_type,
            ),
            sender_account_id=transaction.sender_account_id,
            receiver_account_id=transaction.receiver_account_id,
            amount=transaction.amount,
            currency=transaction.currency,
            status=transaction.status,
            idempotency_key=transaction.idempotency_key,
            risk_score=transaction.risk_score,
            risk_decision=transaction.risk_decision,
            risk_processed_at=transaction.risk_processed_at,
            created_at=transaction.created_at,
            updated_at=transaction.updated_at,
        )
        for transaction in transactions
    ]


# ---------------------------------------------------------------------
# System checks
# ---------------------------------------------------------------------


@router.get("/system-checks")
def manager_system_checks(
    manager: CurrentAdmin,
    db: DBSession,
) -> dict[str, str | int]:
    checks: dict[str, str | int] = {
        "database": "error",
        "redis": "error",
        "users": 0,
        "merchants": 0,
        "accounts": 0,
        "transactions": 0,
        "cash_operations": 0,
    }

    try:
        db.execute(select(1))
        checks["database"] = "ok"

        checks["users"] = db.scalar(
            select(func.count(User.id)),
        ) or 0

        checks["merchants"] = db.scalar(
            select(func.count(Merchant.id)),
        ) or 0

        checks["accounts"] = db.scalar(
            select(func.count(Account.id)),
        ) or 0

        checks["transactions"] = db.scalar(
            select(func.count(Transaction.id)),
        ) or 0

        checks["cash_operations"] = db.scalar(
            select(func.count(CashOperation.id)),
        ) or 0

    except SQLAlchemyError:
        pass

    try:
        redis_client = Redis.from_url(settings.redis_url)
        redis_client.ping()
        redis_client.close()
        checks["redis"] = "ok"
    except Exception:  # noqa: BLE001
        checks["redis"] = "error"

    return checks