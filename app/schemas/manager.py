from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.transaction import TransactionType


class ManagerUserResponse(BaseModel):
    id: UUID
    name: str
    email: str
    role: str
    account_id: UUID | None
    balance: Decimal | None
    currency: str | None


class ManagerMerchantResponse(BaseModel):
    id: UUID
    name: str
    email: str
    account_id: UUID | None
    balance: Decimal | None
    currency: str | None


class ManagerAccountResponse(BaseModel):
    id: UUID

    user_id: UUID | None
    merchant_id: UUID | None

    owner_type: Literal["USER", "MERCHANT"]
    owner_name: str
    owner_email: str

    balance: Decimal
    currency: str
    version: int
    created_at: datetime
    updated_at: datetime


class CashOperationCreate(BaseModel):
    account_id: UUID

    operation_type: Literal["CREDIT", "DEBIT"]

    amount: Decimal = Field(
        gt=0,
        max_digits=18,
        decimal_places=2,
    )

    currency: str = Field(
        min_length=3,
        max_length=3,
    )

    reason: str = Field(
        min_length=1,
        max_length=255,
    )


class CashOperationResponse(BaseModel):
    id: UUID
    account_id: UUID
    manager_id: UUID
    operation_type: str
    amount: Decimal
    currency: str
    balance_before: Decimal
    balance_after: Decimal
    reason: str
    idempotency_key: str
    created_at: datetime


class ManagerTransferCreate(BaseModel):
    sender_account_id: UUID
    transaction_type: TransactionType
    receiver_account_id: UUID

    amount: Decimal = Field(
        gt=0,
        max_digits=18,
        decimal_places=2,
    )

    currency: str = Field(
        min_length=3,
        max_length=3,
    )

    payment_token: str = Field(
        min_length=1,
        max_length=255,
    )


class ManagerTransactionResponse(BaseModel):
    id: UUID

    transaction_type: TransactionType
    sender_account_id: UUID
    receiver_account_id: UUID

    amount: Decimal
    currency: str
    status: str

    idempotency_key: str

    risk_score: Decimal | None
    risk_decision: str | None
    risk_processed_at: datetime | None

    created_at: datetime
    updated_at: datetime