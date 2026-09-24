from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from time import sleep
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import Account, Merchant, RiskJob, Transaction, User
from app.services.risk_engine import calculate_risk_score

NEW_MERCHANT_WINDOW_DAYS: Final = 30
DEFAULT_MAX_ATTEMPTS: Final = 3
DEFAULT_RETRY_DELAY_SECONDS: Final = 5


def utc_now() -> datetime:
    return datetime.now(UTC)


def _get_owner_created_at(
    db: Session,
    account: Account,
) -> datetime:
    if account.user_id is not None:
        user = db.get(User, account.user_id)
        if user is None:
            raise LookupError(
                f"User {account.user_id} was not found.",
            )
        return user.created_at

    if account.merchant_id is not None:
        merchant = db.get(Merchant, account.merchant_id)
        if merchant is None:
            raise LookupError(
                f"Merchant {account.merchant_id} was not found.",
            )
        return merchant.created_at

    raise LookupError(
        f"Account {account.id} has no valid owner.",
    )


def _is_new_receiver_merchant(
    db: Session,
    account: Account,
    now: datetime,
) -> bool:
    if account.merchant_id is None:
        return False

    merchant = db.get(Merchant, account.merchant_id)
    if merchant is None:
        raise LookupError(
            f"Merchant {account.merchant_id} was not found.",
        )

    return merchant.created_at >= (
        now - timedelta(days=NEW_MERCHANT_WINDOW_DAYS)
    )


def _lock_transfer_accounts(
    db: Session,
    sender_account_id,
    receiver_account_id,
) -> tuple[Account, Account]:
    """
    Lock both accounts in deterministic UUID order.

    Deterministic locking prevents opposite-direction transfers from
    acquiring the two account locks in different orders.
    """
    account_ids = sorted(
        [sender_account_id, receiver_account_id],
        key=str,
    )

    accounts = db.scalars(
        select(Account)
        .where(Account.id.in_(account_ids))
        .order_by(Account.id)
        .with_for_update(),
    ).all()

    if len(accounts) != 2:
        raise LookupError(
            "Sender or receiver account was not found during settlement.",
        )

    account_by_id = {
        account.id: account
        for account in accounts
    }

    sender = account_by_id.get(sender_account_id)
    receiver = account_by_id.get(receiver_account_id)

    if sender is None or receiver is None:
        raise LookupError(
            "Sender or receiver account was not found during settlement.",
        )

    return sender, receiver


def process_next_risk_job(
    db: Session,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    retry_delay_seconds: int = DEFAULT_RETRY_DELAY_SECONDS,
) -> bool:
    """
    Claim and process one available risk job.

    PostgreSQL FOR UPDATE SKIP LOCKED ensures concurrent workers do not
    claim the same pending job.

    A transaction reserves sender funds when created.

    Risk outcomes:
        ALLOW  -> credit receiver and complete transaction.
        BLOCK  -> release sender reservation and fail transaction.
        REVIEW -> keep transaction pending for manual review.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1.")

    if retry_delay_seconds < 0:
        raise ValueError("retry_delay_seconds must not be negative.")

    with db.begin():
        now = utc_now()

        # ---------------------------------------------------------
        # 1. Claim one available risk job
        # ---------------------------------------------------------
        job = db.scalar(
            select(RiskJob)
            .where(
                RiskJob.status == "PENDING",
                RiskJob.available_at <= now,
            )
            .order_by(
                RiskJob.available_at.asc(),
                RiskJob.created_at.asc(),
            )
            .limit(1)
            .with_for_update(skip_locked=True),
        )

        if job is None:
            return False

        job.status = "PROCESSING"
        job.attempts += 1
        job.updated_at = now

        # ---------------------------------------------------------
        # 2. Load transaction
        # ---------------------------------------------------------
        transaction = db.get(Transaction, job.transaction_id)

        if transaction is None:
            raise LookupError(
                f"Transaction {job.transaction_id} was not found.",
            )

        # ---------------------------------------------------------
        # 3. Load sender and receiver accounts
        # ---------------------------------------------------------
        sender_account = db.get(
            Account,
            transaction.sender_account_id,
        )

        receiver_account = db.get(
            Account,
            transaction.receiver_account_id,
        )

        if sender_account is None:
            raise LookupError(
                f"Sender account {transaction.sender_account_id} was not found.",
            )

        if receiver_account is None:
            raise LookupError(
                f"Receiver account {transaction.receiver_account_id} was not found.",
            )

        # ---------------------------------------------------------
        # 4. Risk context
        # ---------------------------------------------------------
        one_hour_ago = now - timedelta(hours=1)

        transactions_last_hour = db.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.sender_account_id == transaction.sender_account_id,
                Transaction.id != transaction.id,
                Transaction.created_at >= one_hour_ago,
            ),
        )

        sender_owner_created_at = _get_owner_created_at(
            db,
            sender_account,
        )

        account_age_days = max(
            (now - sender_owner_created_at).days,
            0,
        )

        is_new_merchant = _is_new_receiver_merchant(
            db,
            receiver_account,
            now,
        )

        # ---------------------------------------------------------
        # 5. Calculate risk
        # ---------------------------------------------------------
        try:
            result = calculate_risk_score(
                amount=float(transaction.amount),
                transactions_last_hour=int(
                    transactions_last_hour or 0,
                ),
                account_age_days=account_age_days,
                is_new_merchant=is_new_merchant,
            )
        except Exception as exc:  # noqa: BLE001
            job.last_error = str(exc)[:1000]

            if job.attempts >= max_attempts:
                job.status = "FAILED"
                job.available_at = now
            else:
                job.status = "PENDING"
                job.available_at = now + timedelta(
                    seconds=retry_delay_seconds,
                )

            job.updated_at = utc_now()

            return True

        # ---------------------------------------------------------
        # 6. Store risk result
        # ---------------------------------------------------------
        transaction.risk_score = Decimal(str(result.score))
        transaction.risk_decision = result.decision
        transaction.risk_processed_at = utc_now()

        # ---------------------------------------------------------
        # 7. Settle according to risk decision
        # ---------------------------------------------------------
        if result.decision in {"ALLOW", "BLOCK"}:
            sender, receiver = _lock_transfer_accounts(
                db,
                transaction.sender_account_id,
                transaction.receiver_account_id,
            )

            if result.decision == "ALLOW":
                receiver.balance += transaction.amount
                receiver.version += 1
                receiver.updated_at = now

                transaction.status = "COMPLETED"

            else:
                sender.balance += transaction.amount
                sender.version += 1
                sender.updated_at = now

                transaction.status = "FAILED"

        elif result.decision == "REVIEW":
            # Funds remain reserved until a manual review workflow
            # explicitly resolves the transaction.
            transaction.status = "PENDING"

        else:
            raise ValueError(
                f"Unsupported risk decision: {result.decision}",
            )

        transaction.updated_at = utc_now()

        # ---------------------------------------------------------
        # 8. Mark risk job complete
        # ---------------------------------------------------------
        job.status = "COMPLETED"
        job.last_error = None
        job.updated_at = utc_now()

        return True


def run_worker(
    poll_interval_seconds: float = 1.0,
) -> None:
    """Continuously poll PostgreSQL for pending risk jobs."""
    if poll_interval_seconds < 0:
        raise ValueError(
            "poll_interval_seconds must not be negative.",
        )

    while True:
        with SessionLocal() as db:
            processed = process_next_risk_job(db)

        if not processed:
            sleep(poll_interval_seconds)


if __name__ == "__main__":
    run_worker()