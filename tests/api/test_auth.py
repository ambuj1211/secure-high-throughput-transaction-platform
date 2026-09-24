from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt

from app.core.config import settings


def test_register_success(client):
    email = f"auth-{uuid4()}@test.local"

    response = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Auth Test User",
            "email": email,
            "password": "StrongPass123",
        },
    )

    assert response.status_code == 201

    body = response.json()

    assert body["name"] == "Auth Test User"
    assert body["email"] == email
    assert body["role"] == "user"
    assert "password" not in body
    assert "password_hash" not in body


def test_duplicate_registration_rejected(client):
    email = f"duplicate-{uuid4()}@test.local"

    payload = {
        "name": "Duplicate Test User",
        "email": email,
        "password": "StrongPass123",
    }

    first = client.post(
        "/api/v1/auth/register",
        json=payload,
    )

    second = client.post(
        "/api/v1/auth/register",
        json=payload,
    )

    assert first.status_code == 201
    assert second.status_code == 409


def test_login_success(client):
    email = f"login-{uuid4()}@test.local"
    password = "StrongPass123"

    register_response = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Login Test User",
            "email": email,
            "password": password,
        },
    )

    assert register_response.status_code == 201

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": email,
            "password": password,
        },
    )

    assert login_response.status_code == 200

    body = login_response.json()

    assert body["token_type"] == "bearer"
    assert isinstance(body["access_token"], str)
    assert body["access_token"]


def test_login_wrong_password_rejected(client):
    email = f"wrong-password-{uuid4()}@test.local"

    client.post(
        "/api/v1/auth/register",
        json={
            "name": "Wrong Password User",
            "email": email,
            "password": "CorrectPass123",
        },
    )

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": email,
            "password": "WrongPass123",
        },
    )

    assert response.status_code == 401


def test_me_requires_authentication(client):
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401


def test_me_returns_authenticated_user(
    client,
    transaction_test_data,
    auth_headers,
):
    response = client.get(
        "/api/v1/auth/me",
        headers=auth_headers,
    )

    assert response.status_code == 200

    body = response.json()

    assert body["id"] == transaction_test_data["user_id"]
    assert body["role"] == "user"


def test_invalid_token_rejected(client):
    response = client.get(
        "/api/v1/auth/me",
        headers={
            "Authorization": "Bearer definitely-not-a-valid-jwt",
        },
    )

    assert response.status_code == 401


def test_expired_token_rejected(client, transaction_test_data):
    expired_token = jwt.encode(
        {
            "sub": transaction_test_data["user_id"],
            "role": "user",
            "exp": datetime.now(UTC) - timedelta(minutes=1),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )

    response = client.get(
        "/api/v1/auth/me",
        headers={
            "Authorization": f"Bearer {expired_token}",
        },
    )

    assert response.status_code == 401


def test_user_cannot_access_admin_endpoint(
    client,
    auth_headers,
):
    response = client.get(
        "/api/v1/auth/admin-check",
        headers=auth_headers,
    )

    assert response.status_code == 403


def test_register_creates_zero_balance_account(
    client,
    db,
):
    from decimal import Decimal

    from app.models import Account

    email = f"account-{uuid4()}@test.local"

    response = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Account Test User",
            "email": email,
            "password": "StrongPass123",
        },
    )

    assert response.status_code == 201

    user_id = response.json()["id"]

    account = (
        db.query(Account)
        .filter(
            Account.user_id == user_id,
        )
        .one()
    )

    assert account.balance == Decimal("0.00")
    assert account.currency == "INR"
    assert account.version == 0
