from decimal import Decimal
from uuid import uuid4

from app.db.session import SessionLocal
from app.models import Account, RiskJob, Transaction


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
            "transaction_type": "P2M",
            "receiver_account_id": transaction_test_data["merchant_account_id"],
            "amount": "2000.00",
            "currency": "INR",
            "payment_token": "synthetic-token-001",
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
    assert body["currency"] == "INR"
    assert body["status"] == "PENDING"
    assert body["idempotency_key"] == idempotency_key

    with SessionLocal() as db:
        account = db.get(
            Account,
            transaction_test_data["account_id"],
        )

        assert account is not None
        assert account.balance == Decimal("8000.00")


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
            "transaction_type": "P2M",
            "receiver_account_id": transaction_test_data["merchant_account_id"],
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
        headers={
            "Idempotency-Key": str(uuid4()),
        },
        json={
            "transaction_type": "P2M",
            "receiver_account_id": transaction_test_data["merchant_account_id"],
            "amount": "100.00",
            "currency": "INR",
            "payment_token": "synthetic-token-003",
        },
    )

    assert response.status_code == 401


def test_transaction_fails_for_unknown_receiver_account(
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
            "transaction_type": "P2M",
            "receiver_account_id": str(uuid4()),
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
            "transaction_type": "P2M",
            "receiver_account_id": transaction_test_data["merchant_account_id"],
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
        "transaction_type": "P2M",
        "receiver_account_id": transaction_test_data["merchant_account_id"],
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

    first_body = first_response.json()
    second_body = second_response.json()

    assert first_body["id"] == second_body["id"]

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
            "transaction_type": "P2M",
            "receiver_account_id": transaction_test_data["merchant_account_id"],
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
            "transaction_type": "P2M",
            "receiver_account_id": transaction_test_data["merchant_account_id"],
            "amount": "3000.00",
            "currency": "INR",
            "payment_token": "synthetic-token-conflict",
        },
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 409


def test_transaction_creates_risk_job(
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
            "transaction_type": "P2M",
            "receiver_account_id": transaction_test_data["merchant_account_id"],
            "amount": "2000.00",
            "currency": "INR",
            "payment_token": "synthetic-risk-job-token",
        },
    )

    assert response.status_code == 201

    transaction_id = response.json()["id"]

    with SessionLocal() as db:
        jobs = (
            db.query(RiskJob)
            .filter(
                RiskJob.transaction_id == transaction_id,
            )
            .all()
        )

        assert len(jobs) == 1
        assert jobs[0].status == "PENDING"
        assert jobs[0].attempts == 0


def test_repeated_idempotent_request_creates_only_one_risk_job(
    client,
    transaction_test_data,
    auth_headers,
) -> None:
    idempotency_key = str(uuid4())

    payload = {
        "transaction_type": "P2M",
        "receiver_account_id": transaction_test_data["merchant_account_id"],
        "amount": "1000.00",
        "currency": "INR",
        "payment_token": "synthetic-risk-job-idempotent",
    }

    headers = {
        **auth_headers,
        "Idempotency-Key": idempotency_key,
    }

    first = client.post(
        "/api/v1/transactions",
        headers=headers,
        json=payload,
    )

    second = client.post(
        "/api/v1/transactions",
        headers=headers,
        json=payload,
    )

    assert first.status_code == 201
    assert second.status_code == 201

    first_body = first.json()
    second_body = second.json()

    assert first_body["id"] == second_body["id"]

    with SessionLocal() as db:
        jobs = (
            db.query(RiskJob)
            .filter(
                RiskJob.transaction_id == first_body["id"],
            )
            .all()
        )

        assert len(jobs) == 1