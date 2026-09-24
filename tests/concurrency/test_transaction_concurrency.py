from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from app.models import Account, Transaction


def test_concurrent_same_idempotency_key_does_not_double_debit(
    transaction_test_data,
    auth_headers,
):
    payload = {
        "transaction_type": "P2M",
        "receiver_account_id": transaction_test_data["merchant_account_id"],
        "amount": "2000.00",
        "currency": "INR",
        "payment_token": "synthetic-concurrent-token",
    }

    def send_request():
        with TestClient(app) as client:
            return client.post(
                "/api/v1/transactions",
                headers={
                    **auth_headers,
                    "Idempotency-Key": "concurrent-key-001",
                },
                json=payload,
            )

    with ThreadPoolExecutor(max_workers=8) as executor:
        responses = list(
            executor.map(
                lambda _: send_request(),
                range(8),
            )
        )

    assert all(response.status_code == 201 for response in responses)

    transaction_ids = {
        response.json()["id"]
        for response in responses
    }

    assert len(transaction_ids) == 1

    with SessionLocal() as db:
        account = db.get(
            Account,
            transaction_test_data["account_id"],
        )

        assert account is not None
        assert account.balance == Decimal("8000.00")

        transactions = (
            db.query(Transaction)
            .filter(
                Transaction.idempotency_key == "concurrent-key-001",
            )
            .all()
        )

        assert len(transactions) == 1


def test_concurrent_transactions_preserve_account_consistency(
    transaction_test_data,
    auth_headers,
):
    def send_request(index: int):
        with TestClient(app) as client:
            return client.post(
                "/api/v1/transactions",
                headers={
                    **auth_headers,
                    "Idempotency-Key": f"concurrent-key-{index}",
                },
                json={
                    "transaction_type": "P2M",
                    "receiver_account_id": transaction_test_data[
                        "merchant_account_id"
                    ],
                    "amount": "2000.00",
                    "currency": "INR",
                    "payment_token": f"synthetic-token-{index}",
                },
            )

    with ThreadPoolExecutor(max_workers=6) as executor:
        responses = list(
            executor.map(
                send_request,
                range(6),
            )
        )

    status_codes = [response.status_code for response in responses]

    assert status_codes.count(201) == 5
    assert status_codes.count(409) == 1

    with SessionLocal() as db:
        account = db.get(
            Account,
            transaction_test_data["account_id"],
        )

        assert account is not None
        assert account.balance == Decimal("0.00")

        transactions = (
            db.query(Transaction)
            .filter(
                Transaction.sender_account_id
                == transaction_test_data["account_id"],
            )
            .all()
        )

        assert len(transactions) == 5

        total_amount = sum(
            transaction.amount
            for transaction in transactions
        )

        assert total_amount == Decimal("10000.00")