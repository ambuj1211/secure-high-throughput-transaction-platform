from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, CashOperation
from app.schemas.manager import CashOperationCreate
from app.services.exceptions import (
    AccountNotFoundError,
    IdempotencyConflictError,
    InsufficientFundsError,
)


def perform_cash_operation(
    db: Session,
    manager_id,
    request: CashOperationCreate,
    idempotency_key: str,
) -> tuple[CashOperation, bool]:
    key = idempotency_key.strip()

    existing = db.scalar(
        select(CashOperation).where(
            CashOperation.idempotency_key == key,
        )
    )

    if existing is not None:
        same_request = (
            existing.account_id == request.account_id
            and existing.operation_type == request.operation_type
            and existing.amount == request.amount
            and existing.currency == request.currency
        )

        if not same_request:
            raise IdempotencyConflictError(
                "Idempotency key was already used for a different cash operation."
            )

        return existing, False

    account = db.scalar(
        select(Account).where(Account.id == request.account_id).with_for_update()
    )

    if account is None:
        raise AccountNotFoundError("Account not found.")

    if account.currency != request.currency:
        raise ValueError("Account and cash-operation currencies must match.")

    balance_before = account.balance
    amount = request.amount

    if request.operation_type == "DEBIT":
        if account.balance < amount:
            raise InsufficientFundsError("Insufficient account balance.")

        account.balance -= amount

    else:
        account.balance += amount

    balance_after = account.balance

    account.version += 1
    account.updated_at = datetime.now(UTC)

    operation = CashOperation(
        account_id=account.id,
        manager_id=manager_id,
        operation_type=request.operation_type,
        amount=amount,
        currency=request.currency,
        balance_before=balance_before,
        balance_after=balance_after,
        reason=request.reason.strip(),
        idempotency_key=key,
    )

    db.add(operation)
    db.commit()
    db.refresh(operation)

    return operation, True
