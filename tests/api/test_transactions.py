from uuid import uuid4

from app.db.session import SessionLocal
from app.models import Account, Transaction


def test_create_transaction_success(
    client,
    transaction_test_data,
    auth_headers,
) -> None:
    idempotency_key = str(uuid4())

    response = client.post(
        "/api/v1/transactions",
        headers={
            **auth_headers,
            "Idempotency-Key": idempotency_key,
        },
        json={
            "merchant_id": transaction_test_data["merchant_id"],
            "amount": "2000.00",
            "currency": "INR",
            "payment_token": "synthetic-token-001",
        },
    )

    assert response.status_code == 201

    body = response.json()

    assert body["user_id"] == transaction_test_data["user_id"]
    assert body["merchant_id"] == transaction_test_data["merchant_id"]
    assert body["amount"] == "2000.00"
    assert body["status"] == "PENDING"

    with SessionLocal() as db:
        account = db.get(
            Account,
            transaction_test_data["account_id"],
        )

        assert account.balance == 8000


def test_transaction_fails_for_insufficient_funds(
    client,
    transaction_test_data,
    auth_headers,
) -> None:
    response = client.post(
        "/api/v1/transactions",
        headers={
            **auth_headers,
            "Idempotency-Key": str(uuid4()),
        },
        json={
            "merchant_id": transaction_test_data["merchant_id"],
            "amount": "20000.00",
            "currency": "INR",
            "payment_token": "synthetic-token-002",
        },
    )

    assert response.status_code == 409


def test_transaction_requires_authentication(
    client,
    transaction_test_data,
) -> None:
    response = client.post(
        "/api/v1/transactions",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "merchant_id": transaction_test_data["merchant_id"],
            "amount": "100.00",
            "currency": "INR",
            "payment_token": "synthetic-token-003",
        },
    )

    assert response.status_code == 401


def test_transaction_fails_for_unknown_merchant(
    client,
    auth_headers,
) -> None:
    response = client.post(
        "/api/v1/transactions",
        headers={
            **auth_headers,
            "Idempotency-Key": str(uuid4()),
        },
        json={
            "merchant_id": str(uuid4()),
            "amount": "100.00",
            "currency": "INR",
            "payment_token": "synthetic-token-004",
        },
    )

    assert response.status_code == 404


def test_missing_idempotency_key_rejected(
    client,
    transaction_test_data,
    auth_headers,
) -> None:
    response = client.post(
        "/api/v1/transactions",
        headers=auth_headers,
        json={
            "merchant_id": transaction_test_data["merchant_id"],
            "amount": "100.00",
            "currency": "INR",
            "payment_token": "synthetic-token-005",
        },
    )

    assert response.status_code == 422


def test_repeated_idempotent_request_does_not_double_debit(
    client,
    transaction_test_data,
    auth_headers,
) -> None:
    idempotency_key = str(uuid4())

    payload = {
        "merchant_id": transaction_test_data["merchant_id"],
        "amount": "2000.00",
        "currency": "INR",
        "payment_token": "synthetic-token-idempotent",
    }

    headers = {
        **auth_headers,
        "Idempotency-Key": idempotency_key,
    }

    first_response = client.post(
        "/api/v1/transactions",
        headers=headers,
        json=payload,
    )

    second_response = client.post(
        "/api/v1/transactions",
        headers=headers,
        json=payload,
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 201

    assert first_response.json()["id"] == second_response.json()["id"]

    with SessionLocal() as db:
        account = db.get(
            Account,
            transaction_test_data["account_id"],
        )

        assert account.balance == 8000

        transactions = (
            db.query(Transaction)
            .filter(
                Transaction.idempotency_key == idempotency_key,
            )
            .all()
        )

        assert len(transactions) == 1


def test_reused_idempotency_key_with_different_request_rejected(
    client,
    transaction_test_data,
    auth_headers,
) -> None:
    idempotency_key = str(uuid4())

    first_response = client.post(
        "/api/v1/transactions",
        headers={
            **auth_headers,
            "Idempotency-Key": idempotency_key,
        },
        json={
            "merchant_id": transaction_test_data["merchant_id"],
            "amount": "2000.00",
            "currency": "INR",
            "payment_token": "synthetic-token-conflict",
        },
    )

    second_response = client.post(
        "/api/v1/transactions",
        headers={
            **auth_headers,
            "Idempotency-Key": idempotency_key,
        },
        json={
            "merchant_id": transaction_test_data["merchant_id"],
            "amount": "3000.00",
            "currency": "INR",
            "payment_token": "synthetic-token-conflict",
        },
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 409
