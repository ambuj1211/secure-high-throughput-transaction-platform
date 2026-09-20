import logging
import time
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, Merchant, RiskJob, Transaction
from app.schemas.transaction import TransactionCreate
from app.services.exceptions import (
    AccountNotFoundError,
    IdempotencyConflictError,
    InsufficientFundsError,
    MerchantNotFoundError,
)

logger = logging.getLogger(__name__)

# Log one transaction-service timing sample every N calls.
_PERF_SAMPLE_EVERY = 50
_perf_counter = 0


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

    Performance instrumentation is sampled to avoid logging every
    request.
    """
    global _perf_counter

    _perf_counter += 1
    perf_sample = _perf_counter % _PERF_SAMPLE_EVERY == 0
    perf_start = time.perf_counter()

    merchant_ms = 0.0
    account_lock_ms = 0.0
    idempotency_recheck_ms = 0.0
    transaction_flush_ms = 0.0
    risk_job_flush_ms = 0.0
    commit_ms = 0.0

    transaction: Transaction

    with db.begin():
        # ---------------------------------------------------------
        # 1. Initial idempotency lookup
        # ---------------------------------------------------------
        existing = db.scalar(
            select(Transaction).where(
                Transaction.idempotency_key == idempotency_key
            )
        )

        if existing is not None:
            if _matches_existing_request(existing, user_id, request):
                return existing

            raise IdempotencyConflictError(
                "Idempotency key was already used with a different request."
            )

        # ---------------------------------------------------------
        # 2. Merchant lookup
        # ---------------------------------------------------------
        phase_start = time.perf_counter()

        merchant = db.scalar(
            select(Merchant).where(Merchant.id == request.merchant_id)
        )

        merchant_ms = (time.perf_counter() - phase_start) * 1000

        if merchant is None:
            raise MerchantNotFoundError("Merchant not found.")

        # Use one timestamp for all writes in this transaction.
        now = utc_now()

        # ---------------------------------------------------------
        # 3. Account lookup + row lock
        # ---------------------------------------------------------
        phase_start = time.perf_counter()

        account = db.scalar(
            select(Account)
            .where(Account.user_id == user_id)
            .with_for_update()
        )

        account_lock_ms = (time.perf_counter() - phase_start) * 1000

        if account is None:
            raise AccountNotFoundError("Account not found.")

        # ---------------------------------------------------------
        # 4. Re-check idempotency after acquiring account lock
        # ---------------------------------------------------------
        phase_start = time.perf_counter()

        existing = db.scalar(
            select(Transaction).where(
                Transaction.idempotency_key == idempotency_key
            )
        )

        idempotency_recheck_ms = (
            time.perf_counter() - phase_start
        ) * 1000

        if existing is not None:
            if _matches_existing_request(existing, user_id, request):
                return existing

            raise IdempotencyConflictError(
                "Idempotency key was already used with a different request."
            )

        # ---------------------------------------------------------
        # 5. Validate currency and balance
        # ---------------------------------------------------------
        if account.currency != request.currency:
            raise ValueError(
                "Account and transaction currencies must match."
            )

        if account.balance < request.amount:
            raise InsufficientFundsError(
                "Insufficient account balance."
            )

        # ---------------------------------------------------------
        # 6. Debit account
        # ---------------------------------------------------------
        account.balance -= request.amount
        account.version += 1
        account.updated_at = now

        # ---------------------------------------------------------
        # 7. Create transaction
        # ---------------------------------------------------------
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

        phase_start = time.perf_counter()

        db.flush()

        transaction_flush_ms = (
            time.perf_counter() - phase_start
        ) * 1000

        # ---------------------------------------------------------
        # 8. Create risk job
        # ---------------------------------------------------------
        risk_job = RiskJob(
            transaction_id=transaction.id,
            status="PENDING",
            attempts=0,
            available_at=now,
        )

        db.add(risk_job)

        phase_start = time.perf_counter()

        db.flush()

        risk_job_flush_ms = (
            time.perf_counter() - phase_start
        ) * 1000

        # Start timer immediately before leaving the transaction
        # context. Exiting db.begin() performs the COMMIT.
        commit_start = time.perf_counter()

    # The db.begin() context has now committed.
    commit_ms = (time.perf_counter() - commit_start) * 1000
    total_ms = (time.perf_counter() - perf_start) * 1000

    if perf_sample:
        logger.warning(
            (
                "TX_PERF total=%.2fms merchant=%.2fms "
                "account_lock=%.2fms idempotency_recheck=%.2fms "
                "transaction_flush=%.2fms risk_job_flush=%.2fms "
                "commit=%.2fms"
            ),
            total_ms,
            merchant_ms,
            account_lock_ms,
            idempotency_recheck_ms,
            transaction_flush_ms,
            risk_job_flush_ms,
            commit_ms,
        )

    return transaction