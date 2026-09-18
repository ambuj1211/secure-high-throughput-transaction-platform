from collections.abc import Generator
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.main import app
from app.models import Account, Merchant, RiskJob, Transaction, User


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def db() -> Generator[Session, None, None]:
    session = SessionLocal()

    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def transaction_test_data(
    db: Session,
) -> Generator[dict[str, str], None, None]:
    user = User(
        name="API Test User",
        email=f"user-{uuid4()}@example.com",
    )

    merchant = Merchant(
        name="API Test Merchant",
        email=f"merchant-{uuid4()}@example.com",
    )

    db.add_all([user, merchant])
    db.flush()

    account = Account(
        user_id=user.id,
        balance=Decimal("10000.00"),
        currency="INR",
    )

    db.add(account)
    db.commit()

    data = {
        "user_id": str(user.id),
        "merchant_id": str(merchant.id),
        "account_id": str(account.id),
    }

    yield data

    # Transactions must be deleted before their referenced
    # users/merchants.
    transaction_ids = db.scalars(
        select(Transaction.id).where(
            Transaction.merchant_id == merchant.id,
        )
    ).all()

    if transaction_ids:
        db.execute(
            delete(RiskJob).where(
                RiskJob.transaction_id.in_(transaction_ids),
            )
        )

    db.execute(
        delete(Transaction).where(
            Transaction.merchant_id == merchant.id,
        )
    )

    db.execute(
        delete(Account).where(
            Account.id == account.id,
        )
    )

    db.execute(
        delete(User).where(
            User.id == user.id,
        )
    )

    db.execute(
        delete(Merchant).where(
            Merchant.id == merchant.id,
        )
    )

    db.commit()


@pytest.fixture
def auth_headers(transaction_test_data):
    from app.core.security import create_access_token

    token = create_access_token(
        user_id=transaction_test_data["user_id"],
        role="user",
    )

    return {
        "Authorization": f"Bearer {token}",
    }
