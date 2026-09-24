from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Event
from uuid import UUID, uuid4

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import RiskJob, Transaction
from app.services.risk_engine import RiskResult
from app.workers import risk_worker


def _create_transaction(
    client,
    transaction_test_data,
    auth_headers,
) -> str:
    response = client.post(
        "/api/v1/transactions",
        headers={
            **auth_headers,
            "Idempotency-Key": str(uuid4()),
        },
        json={
            "transaction_type": "P2M",
            "receiver_account_id": transaction_test_data[
                "merchant_account_id"
            ],
            "amount": "2000.00",
            "currency": "INR",
            "payment_token": "synthetic-worker-token",
        },
    )

    assert response.status_code == 201

    body = response.json()

    assert body["transaction_type"] == "P2M"
    assert body["sender_account_id"] == transaction_test_data["account_id"]
    assert body["receiver_account_id"] == transaction_test_data[
        "merchant_account_id"
    ]
    assert body["amount"] == "2000.00"
    assert body["status"] == "PENDING"

    return body["id"]


def test_worker_processes_pending_risk_job(
    client,
    transaction_test_data,
    auth_headers,
) -> None:
    transaction_id = _create_transaction(
        client,
        transaction_test_data,
        auth_headers,
    )

    with SessionLocal() as db:
        job = db.scalar(
            select(RiskJob).where(
                RiskJob.transaction_id == UUID(transaction_id),
            )
        )

        assert job is not None
        assert job.status == "PENDING"

    with SessionLocal() as db:
        processed = risk_worker.process_next_risk_job(db)

        assert processed is True

    with SessionLocal() as db:
        transaction = db.get(
            Transaction,
            UUID(transaction_id),
        )

        job = db.scalar(
            select(RiskJob).where(
                RiskJob.transaction_id == UUID(transaction_id),
            )
        )

        assert transaction is not None
        assert job is not None

        assert job.status == "COMPLETED"
        assert job.attempts == 1
        assert job.last_error is None

        assert transaction.transaction_type == "P2M"
        assert transaction.sender_account_id == UUID(
            transaction_test_data["account_id"]
        )
        assert transaction.receiver_account_id == UUID(
            transaction_test_data["merchant_account_id"]
        )

        assert transaction.risk_score == Decimal("38.00")
        assert transaction.risk_decision == "ALLOW"
        assert transaction.risk_processed_at is not None
        assert transaction.status == "COMPLETED"


def test_completed_job_is_not_processed_again(
    client,
    transaction_test_data,
    auth_headers,
) -> None:
    transaction_id = _create_transaction(
        client,
        transaction_test_data,
        auth_headers,
    )

    with SessionLocal() as db:
        assert risk_worker.process_next_risk_job(db) is True
        assert risk_worker.process_next_risk_job(db) is False

    with SessionLocal() as db:
        job = db.scalar(
            select(RiskJob).where(
                RiskJob.transaction_id == UUID(transaction_id),
            )
        )

        assert job is not None
        assert job.status == "COMPLETED"
        assert job.attempts == 1


def test_worker_retries_failed_risk_job(
    client,
    transaction_test_data,
    auth_headers,
    monkeypatch,
) -> None:
    transaction_id = _create_transaction(
        client,
        transaction_test_data,
        auth_headers,
    )

    calls = 0

    def fail_once_then_succeed(
        amount: float,
        transactions_last_hour: int,
        account_age_days: int,
        is_new_merchant: bool,
    ) -> RiskResult:
        nonlocal calls
        calls += 1

        if calls == 1:
            raise RuntimeError("synthetic risk failure")

        return RiskResult(
            score=25.0,
            decision="ALLOW",
        )

    monkeypatch.setattr(
        risk_worker,
        "calculate_risk_score",
        fail_once_then_succeed,
    )

    with SessionLocal() as db:
        assert (
            risk_worker.process_next_risk_job(
                db,
                retry_delay_seconds=0,
            )
            is True
        )

    with SessionLocal() as db:
        job = db.scalar(
            select(RiskJob).where(
                RiskJob.transaction_id == UUID(transaction_id),
            )
        )

        assert job is not None
        assert job.status == "PENDING"
        assert job.attempts == 1
        assert "synthetic risk failure" in job.last_error

    with SessionLocal() as db:
        assert (
            risk_worker.process_next_risk_job(
                db,
                retry_delay_seconds=0,
            )
            is True
        )

    with SessionLocal() as db:
        transaction = db.get(
            Transaction,
            UUID(transaction_id),
        )

        job = db.scalar(
            select(RiskJob).where(
                RiskJob.transaction_id == UUID(transaction_id),
            )
        )

        assert transaction is not None
        assert job is not None

        assert job.status == "COMPLETED"
        assert job.attempts == 2
        assert job.last_error is None

        assert transaction.risk_score == Decimal("25.00")
        assert transaction.risk_decision == "ALLOW"
        assert transaction.status == "COMPLETED"


def test_worker_marks_job_failed_after_max_attempts(
    client,
    transaction_test_data,
    auth_headers,
    monkeypatch,
) -> None:
    transaction_id = _create_transaction(
        client,
        transaction_test_data,
        auth_headers,
    )

    def always_fail(
        amount: float,
        transactions_last_hour: int,
        account_age_days: int,
        is_new_merchant: bool,
    ) -> RiskResult:
        raise RuntimeError("permanent synthetic risk failure")

    monkeypatch.setattr(
        risk_worker,
        "calculate_risk_score",
        always_fail,
    )

    with SessionLocal() as db:
        assert (
            risk_worker.process_next_risk_job(
                db,
                max_attempts=2,
                retry_delay_seconds=0,
            )
            is True
        )

    with SessionLocal() as db:
        assert (
            risk_worker.process_next_risk_job(
                db,
                max_attempts=2,
                retry_delay_seconds=0,
            )
            is True
        )

    with SessionLocal() as db:
        job = db.scalar(
            select(RiskJob).where(
                RiskJob.transaction_id == UUID(transaction_id),
            )
        )

        assert job is not None
        assert job.status == "FAILED"
        assert job.attempts == 2
        assert "permanent synthetic risk failure" in job.last_error


def test_skip_locked_prevents_two_workers_claiming_same_job(
    client,
    transaction_test_data,
    auth_headers,
    monkeypatch,
) -> None:
    transaction_id = _create_transaction(
        client,
        transaction_test_data,
        auth_headers,
    )

    started = Event()
    release = Event()

    def slow_risk_calculation(
        amount: float,
        transactions_last_hour: int,
        account_age_days: int,
        is_new_merchant: bool,
    ) -> RiskResult:
        started.set()

        if not release.wait(timeout=5):
            raise RuntimeError("worker test timed out")

        return RiskResult(
            score=20.0,
            decision="ALLOW",
        )

    monkeypatch.setattr(
        risk_worker,
        "calculate_risk_score",
        slow_risk_calculation,
    )

    def run_first_worker() -> bool:
        with SessionLocal() as db:
            return risk_worker.process_next_risk_job(db)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(run_first_worker)

        assert started.wait(timeout=5)

        with SessionLocal() as db:
            second_result = risk_worker.process_next_risk_job(db)

        assert second_result is False

        release.set()

        assert first_future.result(timeout=10) is True

    with SessionLocal() as db:
        transaction = db.get(
            Transaction,
            UUID(transaction_id),
        )

        job = db.scalar(
            select(RiskJob).where(
                RiskJob.transaction_id == UUID(transaction_id),
            )
        )

        assert transaction is not None
        assert job is not None
        assert job.status == "COMPLETED"
        assert job.attempts == 1
        assert transaction.status == "COMPLETED"