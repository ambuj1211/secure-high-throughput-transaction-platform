from decimal import Decimal
from uuid import uuid4

from app.core.security import create_access_token, hash_password
from app.models import Account, User


def manager_headers(user_id):
    token = create_access_token(
        user_id=str(user_id),
        role="admin",
    )

    return {
        "Authorization": f"Bearer {token}",
    }


def create_manager(db):
    manager = User(
        name="Manager Test",
        email=f"manager-{uuid4()}@test.local",
        password_hash=hash_password("ManagerPass123"),
        role="admin",
    )

    db.add(manager)
    db.commit()
    db.refresh(manager)

    return manager


def create_user_with_account(db, balance="100.00"):
    user = User(
        name="Cash Target",
        email=f"cash-{uuid4()}@test.local",
    )

    db.add(user)
    db.flush()

    account = Account(
        user_id=user.id,
        balance=Decimal(balance),
        currency="INR",
    )

    db.add(account)
    db.commit()

    return user, account


def test_manager_can_create_user_with_account(client, db):
    manager = create_manager(db)

    response = client.post(
        "/api/v1/manager/users",
        headers=manager_headers(manager.id),
        json={
            "name": "Manager Created User",
            "email": f"created-{uuid4()}@test.local",
            "password": "StrongPass123",
        },
    )

    assert response.status_code == 201

    body = response.json()

    assert body["role"] == "user"
    assert body["balance"] == "0.00"
    assert body["currency"] == "INR"

    account = db.get(
        Account,
        body["account_id"],
    )

    assert account is not None
    assert account.balance == Decimal("0.00")


def test_normal_user_cannot_use_manager_cash_endpoint(
    client,
    db,
):
    user, account = create_user_with_account(
        db,
        balance="100.00",
    )

    # Deliberately create a token with the real user role.
    token = create_access_token(
        user_id=str(user.id),
        role="user",
    )

    response = client.post(
        "/api/v1/manager/cash",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": str(uuid4()),
        },
        json={
            "account_id": str(account.id),
            "operation_type": "CREDIT",
            "amount": "10.00",
            "currency": "INR",
            "reason": "Unauthorized credit test",
        },
    )

    assert response.status_code == 403


def test_manager_can_credit_and_debit_account(
    client,
    db,
):
    manager = create_manager(db)

    _, account = create_user_with_account(
        db,
        balance="100.00",
    )

    credit_key = str(uuid4())

    credit = client.post(
        "/api/v1/manager/cash",
        headers={
            **manager_headers(manager.id),
            "Idempotency-Key": credit_key,
        },
        json={
            "account_id": str(account.id),
            "operation_type": "CREDIT",
            "amount": "50.00",
            "currency": "INR",
            "reason": "Cash deposit",
        },
    )

    assert credit.status_code == 201
    assert credit.json()["balance_after"] == "150.00"

    debit = client.post(
        "/api/v1/manager/cash",
        headers={
            **manager_headers(manager.id),
            "Idempotency-Key": str(uuid4()),
        },
        json={
            "account_id": str(account.id),
            "operation_type": "DEBIT",
            "amount": "25.00",
            "currency": "INR",
            "reason": "Cash withdrawal",
        },
    )

    assert debit.status_code == 201
    assert debit.json()["balance_after"] == "125.00"


def test_manager_debit_rejects_insufficient_balance(
    client,
    db,
):
    manager = create_manager(db)

    _, account = create_user_with_account(
        db,
        balance="20.00",
    )

    response = client.post(
        "/api/v1/manager/cash",
        headers={
            **manager_headers(manager.id),
            "Idempotency-Key": str(uuid4()),
        },
        json={
            "account_id": str(account.id),
            "operation_type": "DEBIT",
            "amount": "25.00",
            "currency": "INR",
            "reason": "Insufficient debit test",
        },
    )

    assert response.status_code == 409


def test_manager_cash_idempotency_returns_same_operation(
    client,
    db,
):
    manager = create_manager(db)

    _, account = create_user_with_account(
        db,
        balance="100.00",
    )

    key = str(uuid4())

    payload = {
        "account_id": str(account.id),
        "operation_type": "CREDIT",
        "amount": "50.00",
        "currency": "INR",
        "reason": "Idempotency test",
    }

    first = client.post(
        "/api/v1/manager/cash",
        headers={
            **manager_headers(manager.id),
            "Idempotency-Key": key,
        },
        json=payload,
    )

    second = client.post(
        "/api/v1/manager/cash",
        headers={
            **manager_headers(manager.id),
            "Idempotency-Key": key,
        },
        json=payload,
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    db.refresh(account)

    assert account.balance == Decimal("150.00")
