from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, Merchant, Transaction, User
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
    request: TransactionCreate,
) -> bool:
    return (
        transaction.user_id == request.user_id
        and transaction.merchant_id == request.merchant_id
        and transaction.amount == request.amount
        and transaction.currency == request.currency
        and transaction.payment_token == request.payment_token
    )


def create_transaction(
    db: Session,
    request: TransactionCreate,
    idempotency_key: str,
) -> Transaction:
    """
    Create a transaction atomically.

    The account row is locked with SELECT FOR UPDATE so concurrent
    requests cannot both spend the same available balance.
    """

    with db.begin():
        existing = db.scalar(
            select(Transaction).where(Transaction.idempotency_key == idempotency_key)
        )

        if existing is not None:
            if _matches_existing_request(existing, request):
                return existing

            raise IdempotencyConflictError(
                "Idempotency key was already used with a different request."
            )

        user = db.scalar(select(User).where(User.id == request.user_id))

        if user is None:
            raise UserNotFoundError("User not found.")

        merchant = db.scalar(select(Merchant).where(Merchant.id == request.merchant_id))

        if merchant is None:
            raise MerchantNotFoundError("Merchant not found.")

        account = db.scalar(
            select(Account).where(Account.user_id == request.user_id).with_for_update()
        )

        if account is None:
            raise AccountNotFoundError("Account not found.")

        existing = db.scalar(
            select(Transaction).where(Transaction.idempotency_key == idempotency_key)
        )

        if existing is not None:
            if _matches_existing_request(existing, request):
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
            user_id=request.user_id,
            merchant_id=request.merchant_id,
            amount=request.amount,
            currency=request.currency,
            status="PENDING",
            idempotency_key=idempotency_key,
            payment_token=request.payment_token,
        )

        db.add(transaction)
        db.flush()

        return transaction
