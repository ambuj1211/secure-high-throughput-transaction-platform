from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.main import app
from app.models import Account, RiskJob, Transaction, User


def test_transaction_cannot_use_client_supplied_user_id(
    transaction_test_data,
):
    attacker_id = None
    transaction_id = None

    with SessionLocal() as db:
        attacker = User(
            name="BOLA Attacker",
            email=f"bola-{uuid4()}@test.local",
            password_hash=None,
            role="user",
        )
        db.add(attacker)
        db.flush()

        attacker_account = Account(
            user_id=attacker.id,
            balance=5000,
            currency="INR",
        )
        db.add(attacker_account)
        db.commit()

        attacker_id = str(attacker.id)

    attacker_token = create_access_token(
        user_id=attacker_id,
        role="user",
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/transactions",
            headers={
                "Authorization": f"Bearer {attacker_token}",
                "Idempotency-Key": f"bola-{uuid4()}",
            },
            json={
                # Malicious client-supplied victim ID.
                # TransactionCreate should ignore this unknown field.
                "user_id": transaction_test_data["user_id"],
                "merchant_id": transaction_test_data["merchant_id"],
                "amount": "1000.00",
                "currency": "INR",
                "payment_token": "synthetic-bola-token",
            },
        )

    assert response.status_code == 201

    body = response.json()
    transaction_id = body["id"]

    # Identity must come from the JWT, not the request body.
    assert body["user_id"] == attacker_id
    assert body["user_id"] != transaction_test_data["user_id"]

    with SessionLocal() as db:
        attacker_account = (
            db.query(Account).filter(Account.user_id == attacker_id).one()
        )

        victim_account = db.get(
            Account,
            transaction_test_data["account_id"],
        )

        transaction = db.get(
            Transaction,
            transaction_id,
        )

        assert attacker_account.balance == 4000
        assert victim_account.balance == 10000
        assert str(transaction.user_id) == attacker_id

        # Explicitly prove the victim's account was not debited.
        assert transaction.user_id != transaction_test_data["user_id"]

        # Cleanup the attacker's transaction before deleting the attacker.
        risk_job = (
            db.query(RiskJob)
            .filter(RiskJob.transaction_id == transaction.id)
            .one_or_none()
        )

        if risk_job is not None:
            db.delete(risk_job)

        db.delete(transaction)
        db.delete(attacker_account)

        attacker = db.get(User, attacker_id)
        if attacker is not None:
            db.delete(attacker)

        db.commit()
