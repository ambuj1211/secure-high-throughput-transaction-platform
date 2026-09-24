import logging
import time
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, RiskJob, Transaction
from app.schemas.transaction import TransactionCreate
from app.services.exceptions import (
    AccountNotFoundError,
    IdempotencyConflictError,
    InsufficientFundsError,
)

logger = logging.getLogger(__name__)

# Log one transaction-service timing sample every N calls.
_PERF_SAMPLE_EVERY = 50
_perf_counter = 0


def utc_now() -> datetime:
    return datetime.now(UTC)


def _matches_existing_request(
    transaction: Transaction,
    sender_account_id: UUID,
    request: TransactionCreate,
) -> bool:
    return (
        transaction.sender_account_id == sender_account_id
        and transaction.receiver_account_id == request.receiver_account_id
        and transaction.transaction_type == request.transaction_type
        and transaction.amount == request.amount
        and transaction.currency == request.currency
        and transaction.payment_token == request.payment_token
    )


def _validate_transfer_type(
    transaction_type: str,
    sender: Account,
    receiver: Account,
) -> None:
    sender_is_user = sender.user_id is not None
    sender_is_merchant = sender.merchant_id is not None

    receiver_is_user = receiver.user_id is not None
    receiver_is_merchant = receiver.merchant_id is not None

    valid_types = {
        "P2P": sender_is_user and receiver_is_user,
        "P2M": sender_is_user and receiver_is_merchant,
        "M2M": sender_is_merchant and receiver_is_merchant,
        "M2P": sender_is_merchant and receiver_is_user,
    }

    if not valid_types.get(transaction_type, False):
        raise ValueError(
            f"Transaction type {transaction_type} does not match "
            "the sender and receiver account ownership.",
        )


def create_transaction(
    db: Session,
    user_id: UUID,
    request: TransactionCreate,
    idempotency_key: str,
    sender_account_id: UUID | None = None,
) -> Transaction:
    """
    Create a transfer and reserve the sender's funds.

    Normal participant requests:
        sender_account_id is resolved from the authenticated user_id.

    Manager requests:
        sender_account_id is supplied explicitly.

    The sender account is debited immediately as a reservation.
    The receiver is credited only after the risk worker allows the
    transaction. A blocked transaction will release the reservation.

    Both transaction and RiskJob are created atomically.
    """
    global _perf_counter

    _perf_counter += 1
    perf_sample = _perf_counter % _PERF_SAMPLE_EVERY == 0
    perf_start = time.perf_counter()

    account_lock_ms = 0.0
    receiver_lookup_ms = 0.0
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
                Transaction.idempotency_key == idempotency_key,
            ),
        )

        if existing is not None:
            effective_sender_id = sender_account_id

            if effective_sender_id is None:
                account = db.scalar(
                    select(Account).where(Account.user_id == user_id),
                )
                if account is not None:
                    effective_sender_id = account.id

            if effective_sender_id is not None and _matches_existing_request(
                existing,
                effective_sender_id,
                request,
            ):
                return existing

            raise IdempotencyConflictError(
                "Idempotency key was already used with a different request.",
            )

        # ---------------------------------------------------------
        # 2. Resolve sender account
        # ---------------------------------------------------------
        if sender_account_id is None:
            sender_account_id = db.scalar(
                select(Account.id).where(Account.user_id == user_id),
            )

            if sender_account_id is None:
                raise AccountNotFoundError(
                    "Sender account not found.",
                )

        # ---------------------------------------------------------
        # 3. Lock sender account
        # ---------------------------------------------------------
        phase_start = time.perf_counter()

        sender = db.scalar(
            select(Account)
            .where(Account.id == sender_account_id)
            .with_for_update(),
        )

        account_lock_ms = (time.perf_counter() - phase_start) * 1000

        if sender is None:
            raise AccountNotFoundError(
                "Sender account not found.",
            )

        # ---------------------------------------------------------
        # 4. Receiver lookup
        # ---------------------------------------------------------
        phase_start = time.perf_counter()

        receiver = db.scalar(
            select(Account).where(
                Account.id == request.receiver_account_id,
            ),
        )

        receiver_lookup_ms = (time.perf_counter() - phase_start) * 1000

        if receiver is None:
            raise AccountNotFoundError(
                "Receiver account not found.",
            )

        if sender.id == receiver.id:
            raise ValueError(
                "Sender and receiver accounts must be different.",
            )

        # ---------------------------------------------------------
        # 5. Validate transfer type and currency
        # ---------------------------------------------------------
        _validate_transfer_type(
            request.transaction_type,
            sender,
            receiver,
        )

        if sender.currency != request.currency:
            raise ValueError(
                "Sender account and transaction currencies must match.",
            )

        if receiver.currency != request.currency:
            raise ValueError(
                "Receiver account and transaction currencies must match.",
            )

        # ---------------------------------------------------------
        # 6. Check available balance
        # ---------------------------------------------------------
        if sender.balance < request.amount:
            raise InsufficientFundsError(
                "Insufficient account balance.",
            )

        # ---------------------------------------------------------
        # 7. Re-check idempotency after acquiring sender lock
        # ---------------------------------------------------------
        phase_start = time.perf_counter()

        existing = db.scalar(
            select(Transaction).where(
                Transaction.idempotency_key == idempotency_key,
            ),
        )

        idempotency_recheck_ms = (time.perf_counter() - phase_start) * 1000

        if existing is not None:
            if _matches_existing_request(
                existing,
                sender.id,
                request,
            ):
                return existing

            raise IdempotencyConflictError(
                "Idempotency key was already used with a different request.",
            )

        # ---------------------------------------------------------
        # 8. Reserve sender funds
        # ---------------------------------------------------------
        now = utc_now()

        sender.balance -= request.amount
        sender.version += 1
        sender.updated_at = now

        # ---------------------------------------------------------
        # 9. Create transaction
        # ---------------------------------------------------------
        transaction = Transaction(
            transaction_type=request.transaction_type,
            sender_account_id=sender.id,
            receiver_account_id=receiver.id,
            amount=request.amount,
            currency=request.currency,
            payment_token=request.payment_token,
            idempotency_key=idempotency_key,
            status="PENDING",
        )

        db.add(transaction)

        phase_start = time.perf_counter()

        db.flush()

        transaction_flush_ms = (time.perf_counter() - phase_start) * 1000

        # ---------------------------------------------------------
        # 10. Create risk job
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

        risk_job_flush_ms = (time.perf_counter() - phase_start) * 1000

        # Commit occurs when db.begin() exits.
        commit_start = time.perf_counter()

    commit_ms = (time.perf_counter() - commit_start) * 1000
    total_ms = (time.perf_counter() - perf_start) * 1000

    if perf_sample:
        logger.warning(
            (
                "TX_PERF total=%.2fms account_lock=%.2fms "
                "receiver_lookup=%.2fms idempotency_recheck=%.2fms "
                "transaction_flush=%.2fms risk_job_flush=%.2fms "
                "commit=%.2fms"
            ),
            total_ms,
            account_lock_ms,
            receiver_lookup_ms,
            idempotency_recheck_ms,
            transaction_flush_ms,
            risk_job_flush_ms,
            commit_ms,
        )

    return transaction