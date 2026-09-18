from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.session import SessionLocal
from app.models import Account, Merchant, Transaction, User


def test_create_user_merchant_account_transaction() -> None:
    db = SessionLocal()

    try:
        user = User(
            name="Test User",
            email=f"user-{uuid4()}@example.com",
        )

        merchant = Merchant(
            name="Test Merchant",
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
        db.flush()

        transaction = Transaction(
            user_id=user.id,
            merchant_id=merchant.id,
            amount=Decimal("2000.00"),
            currency="INR",
            status="PENDING",
            idempotency_key=f"idem-{uuid4()}",
            payment_token=f"token-{uuid4()}",
        )

        db.add(transaction)
        db.flush()

        assert user.id is not None
        assert merchant.id is not None
        assert account.id is not None
        assert transaction.id is not None
        assert account.balance == Decimal("10000.00")

    finally:
        db.rollback()
        db.close()


def test_negative_transaction_amount_rejected() -> None:
    db = SessionLocal()

    try:
        user = User(
            name="Amount Test User",
            email=f"user-{uuid4()}@example.com",
        )

        merchant = Merchant(
            name="Amount Test Merchant",
            email=f"merchant-{uuid4()}@example.com",
        )

        db.add_all([user, merchant])
        db.flush()

        transaction = Transaction(
            user_id=user.id,
            merchant_id=merchant.id,
            amount=Decimal("-1.00"),
            currency="INR",
            status="PENDING",
            idempotency_key=f"idem-{uuid4()}",
            payment_token=f"token-{uuid4()}",
        )

        db.add(transaction)

        with pytest.raises(IntegrityError):
            db.commit()

        db.rollback()

    finally:
        db.close()


def test_negative_account_balance_rejected() -> None:
    db = SessionLocal()

    try:
        user = User(
            name="Balance Test User",
            email=f"user-{uuid4()}@example.com",
        )

        db.add(user)
        db.flush()

        account = Account(
            user_id=user.id,
            balance=Decimal("-100.00"),
            currency="INR",
        )

        db.add(account)

        with pytest.raises(IntegrityError):
            db.commit()

        db.rollback()

    finally:
        db.close()
