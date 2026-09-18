from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, Merchant, RiskJob, Transaction, User
from app.schemas.transaction import TransactionCreate
from app.services.exceptions import (
    AccountNotFoundError,
    IdempotencyConflictError,
    InsufficientFundsError,
    MerchantNotFoundError,
    UserNotFoundError,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _matches_existing_request(
    transaction: Transaction,
    user_id: UUID,
    request: TransactionCreate,
) -> bool:
    return (
        transaction.user_id == user_id
        and transaction.merchant_id == request.merchant_id
        and transaction.amount == request.amount
        and transaction.currency == request.currency
        and transaction.payment_token == request.payment_token
    )


def create_transaction(
    db: Session,
    user_id: UUID,
    request: TransactionCreate,
    idempotency_key: str,
) -> Transaction:
    """
    Create a transaction atomically.

    The authenticated user_id is supplied by the JWT layer rather than
    being accepted from the client request body.

    The account row is locked with SELECT FOR UPDATE so concurrent
    requests cannot both spend the same available balance.

    The transaction and its risk job are committed in the same
    database transaction.
    """

    with db.begin():
        existing = db.scalar(
            select(Transaction).where(Transaction.idempotency_key == idempotency_key)
        )

        if existing is not None:
            if _matches_existing_request(existing, user_id, request):
                return existing

            raise IdempotencyConflictError(
                "Idempotency key was already used with a different request."
            )

        user = db.scalar(select(User).where(User.id == user_id))

        if user is None:
            raise UserNotFoundError("User not found.")

        merchant = db.scalar(select(Merchant).where(Merchant.id == request.merchant_id))

        if merchant is None:
            raise MerchantNotFoundError("Merchant not found.")

        account = db.scalar(
            select(Account).where(Account.user_id == user_id).with_for_update()
        )

        if account is None:
            raise AccountNotFoundError("Account not found.")

        # Re-check idempotency after acquiring the account lock.
        existing = db.scalar(
            select(Transaction).where(Transaction.idempotency_key == idempotency_key)
        )

        if existing is not None:
            if _matches_existing_request(existing, user_id, request):
                return existing

            raise IdempotencyConflictError(
                "Idempotency key was already used with a different request."
            )

        if account.currency != request.currency:
            raise ValueError("Account and transaction currencies must match.")

        if account.balance < request.amount:
            raise InsufficientFundsError("Insufficient account balance.")

        account.balance -= request.amount
        account.version += 1
        account.updated_at = utc_now()

        transaction = Transaction(
            user_id=user_id,
            merchant_id=request.merchant_id,
            amount=request.amount,
            currency=request.currency,
            payment_token=request.payment_token,
            idempotency_key=idempotency_key,
            status="PENDING",
        )

        db.add(transaction)
        db.flush()

        risk_job = RiskJob(
            transaction_id=transaction.id,
            status="PENDING",
            attempts=0,
            available_at=utc_now(),
        )

        db.add(risk_job)
        db.flush()

        return transaction
