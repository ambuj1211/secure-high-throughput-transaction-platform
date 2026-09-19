from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from app.models import Transaction
from app.services.transaction_analytics import generate_transaction_analytics


def test_generate_transaction_analytics_reads_from_database(
    db,
    transaction_test_data,
) -> None:
    user_id = UUID(transaction_test_data["user_id"])
    merchant_id = UUID(transaction_test_data["merchant_id"])

    now = datetime.now(timezone.utc)

    transactions = [
        Transaction(
            user_id=user_id,
            merchant_id=merchant_id,
            amount=Decimal("100.00"),
            currency="INR",
            status="COMPLETED",
            idempotency_key=f"analytics-{uuid4()}",
            payment_token=f"analytics-token-{uuid4()}",
            risk_decision="ALLOW",
            risk_score=Decimal("10.00"),
            created_at=now - timedelta(hours=2),
        ),
        Transaction(
            user_id=user_id,
            merchant_id=merchant_id,
            amount=Decimal("300.00"),
            currency="INR",
            status="COMPLETED",
            idempotency_key=f"analytics-{uuid4()}",
            payment_token=f"analytics-token-{uuid4()}",
            risk_decision="REVIEW",
            risk_score=Decimal("50.00"),
            created_at=now - timedelta(minutes=30),
        ),
        Transaction(
            user_id=user_id,
            merchant_id=merchant_id,
            amount=Decimal("600.00"),
            currency="INR",
            status="PENDING",
            idempotency_key=f"analytics-{uuid4()}",
            payment_token=f"analytics-token-{uuid4()}",
            risk_decision=None,
            risk_score=None,
            created_at=now - timedelta(minutes=10),
        ),
    ]

    db.add_all(transactions)
    db.commit()

    result = generate_transaction_analytics(db)

    assert result.transaction_count == 3
    assert result.total_amount == Decimal("1000.00")
    assert result.average_amount == Decimal("333.33")

    assert result.status_counts == {
        "COMPLETED": 2,
        "PENDING": 1,
    }

    assert result.risk_decision_counts == {
        "ALLOW": 1,
        "REVIEW": 1,
        "UNPROCESSED": 1,
    }


def test_generate_transaction_analytics_supports_time_range(
    db,
    transaction_test_data,
) -> None:
    user_id = UUID(transaction_test_data["user_id"])
    merchant_id = UUID(transaction_test_data["merchant_id"])

    now = datetime.now(timezone.utc)

    transactions = [
        Transaction(
            user_id=user_id,
            merchant_id=merchant_id,
            amount=Decimal("100.00"),
            currency="INR",
            status="COMPLETED",
            idempotency_key=f"analytics-range-{uuid4()}",
            payment_token=f"analytics-range-token-{uuid4()}",
            risk_decision="ALLOW",
            created_at=now - timedelta(hours=3),
        ),
        Transaction(
            user_id=user_id,
            merchant_id=merchant_id,
            amount=Decimal("250.00"),
            currency="INR",
            status="COMPLETED",
            idempotency_key=f"analytics-range-{uuid4()}",
            payment_token=f"analytics-range-token-{uuid4()}",
            risk_decision="ALLOW",
            created_at=now - timedelta(hours=1),
        ),
        Transaction(
            user_id=user_id,
            merchant_id=merchant_id,
            amount=Decimal("400.00"),
            currency="INR",
            status="FAILED",
            idempotency_key=f"analytics-range-{uuid4()}",
            payment_token=f"analytics-range-token-{uuid4()}",
            risk_decision="BLOCK",
            created_at=now - timedelta(minutes=15),
        ),
    ]

    db.add_all(transactions)
    db.commit()

    start_at = now - timedelta(hours=2)
    end_at = now

    result = generate_transaction_analytics(
        db,
        start_at=start_at,
        end_at=end_at,
    )

    assert result.transaction_count == 2
    assert result.total_amount == Decimal("650.00")
    assert result.average_amount == Decimal("325.00")

    assert result.status_counts == {
        "COMPLETED": 1,
        "FAILED": 1,
    }

    assert result.risk_decision_counts == {
        "ALLOW": 1,
        "BLOCK": 1,
    }
