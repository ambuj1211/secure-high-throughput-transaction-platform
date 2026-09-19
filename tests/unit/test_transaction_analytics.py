from decimal import Decimal

from app.services.transaction_analytics import (
    calculate_transaction_analytics,
)


def test_transaction_analytics_calculates_core_metrics() -> None:
    transactions = [
        {
            "amount": Decimal("100.00"),
            "currency": "INR",
            "status": "COMPLETED",
            "risk_decision": "ALLOW",
        },
        {
            "amount": Decimal("250.00"),
            "currency": "INR",
            "status": "COMPLETED",
            "risk_decision": "ALLOW",
        },
        {
            "amount": Decimal("150.00"),
            "currency": "INR",
            "status": "PENDING",
            "risk_decision": "REVIEW",
        },
        {
            "amount": Decimal("500.00"),
            "currency": "INR",
            "status": "FAILED",
            "risk_decision": "BLOCK",
        },
    ]

    result = calculate_transaction_analytics(transactions)

    assert result.transaction_count == 4
    assert result.total_amount == Decimal("1000.00")
    assert result.average_amount == Decimal("250.00")

    assert result.status_counts == {
        "COMPLETED": 2,
        "PENDING": 1,
        "FAILED": 1,
    }

    assert result.risk_decision_counts == {
        "ALLOW": 2,
        "REVIEW": 1,
        "BLOCK": 1,
    }


def test_unprocessed_transactions_are_grouped_separately() -> None:
    transactions = [
        {
            "amount": Decimal("100.00"),
            "currency": "INR",
            "status": "PENDING",
            "risk_decision": None,
        },
    ]

    result = calculate_transaction_analytics(transactions)

    assert result.transaction_count == 1
    assert result.total_amount == Decimal("100.00")
    assert result.average_amount == Decimal("100.00")
    assert result.risk_decision_counts == {
        "UNPROCESSED": 1,
    }


def test_empty_transaction_dataset() -> None:
    result = calculate_transaction_analytics([])

    assert result.transaction_count == 0
    assert result.total_amount == Decimal("0.00")
    assert result.average_amount == Decimal("0.00")
    assert result.status_counts == {}
    assert result.risk_decision_counts == {}
