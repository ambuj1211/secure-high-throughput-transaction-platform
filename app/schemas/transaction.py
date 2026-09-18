from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TransactionCreate(BaseModel):
    user_id: UUID
    merchant_id: UUID
    amount: Decimal = Field(
        gt=0,
        max_digits=18,
        decimal_places=2,
    )
    currency: str = Field(
        default="INR",
        min_length=3,
        max_length=3,
    )
    payment_token: str = Field(
        min_length=1,
        max_length=255,
    )


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    merchant_id: UUID
    amount: Decimal
    currency: str
    status: str
    idempotency_key: str
    created_at: datetime
    updated_at: datetime
