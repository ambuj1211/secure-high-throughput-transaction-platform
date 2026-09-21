from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from time import sleep
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import Merchant, RiskJob, Transaction, User
from app.services.risk_engine import calculate_risk_score

NEW_MERCHANT_WINDOW_DAYS: Final = 30
DEFAULT_MAX_ATTEMPTS: Final = 3
DEFAULT_RETRY_DELAY_SECONDS: Final = 5


def utc_now() -> datetime:
    return datetime.now(UTC)


def process_next_risk_job(
    db: Session,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    retry_delay_seconds: int = DEFAULT_RETRY_DELAY_SECONDS,
) -> bool:
    """
    Claim and process one available risk job.

    PostgreSQL FOR UPDATE SKIP LOCKED ensures that concurrent workers
    do not claim the same pending job.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1.")

    if retry_delay_seconds < 0:
        raise ValueError("retry_delay_seconds must not be negative.")

    with db.begin():
        now = utc_now()

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
            .with_for_update(skip_locked=True)
        )

        if job is None:
            return False

        job.status = "PROCESSING"
        job.attempts += 1
        job.updated_at = now

        transaction = db.get(Transaction, job.transaction_id)
        if transaction is None:
            raise LookupError(f"Transaction {job.transaction_id} was not found.")

        user = db.get(User, transaction.user_id)
        if user is None:
            raise LookupError(f"User {transaction.user_id} was not found.")

        merchant = db.get(Merchant, transaction.merchant_id)
        if merchant is None:
            raise LookupError(f"Merchant {transaction.merchant_id} was not found.")

        one_hour_ago = now - timedelta(hours=1)

        transactions_last_hour = db.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.user_id == transaction.user_id,
                Transaction.id != transaction.id,
                Transaction.created_at >= one_hour_ago,
            )
        )

        account_age_days = max(
            (now - user.created_at).days,
            0,
        )

        is_new_merchant = merchant.created_at >= (
            now - timedelta(days=NEW_MERCHANT_WINDOW_DAYS)
        )

        try:
            result = calculate_risk_score(
                amount=float(transaction.amount),
                transactions_last_hour=int(transactions_last_hour or 0),
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
                job.available_at = now + timedelta(seconds=retry_delay_seconds)

            job.updated_at = utc_now()
            return True

        transaction.risk_score = Decimal(str(result.score))
        transaction.risk_decision = result.decision
        transaction.risk_processed_at = utc_now()
        transaction.updated_at = utc_now()

        job.status = "COMPLETED"
        job.last_error = None
        job.updated_at = utc_now()

        return True


def run_worker(poll_interval_seconds: float = 1.0) -> None:
    """Continuously poll PostgreSQL for pending risk jobs."""
    if poll_interval_seconds < 0:
        raise ValueError("poll_interval_seconds must not be negative.")

    while True:
        with SessionLocal() as db:
            processed = process_next_risk_job(db)

        if not processed:
            sleep(poll_interval_seconds)


if __name__ == "__main__":
    run_worker()
