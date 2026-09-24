from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

TransactionType = Literal["P2P", "P2M", "M2M", "M2P"]


class TransactionCreate(BaseModel):
    transaction_type: TransactionType

    # Normal user/merchant requests:
    # the backend resolves the sender from the authenticated identity.
    #
    # Manager requests:
    # sender_account_id is supplied explicitly by the manager endpoint.
    sender_account_id: UUID | None = None

    receiver_account_id: UUID

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
    transaction_type: TransactionType
    sender_account_id: UUID
    receiver_account_id: UUID
    amount: Decimal
    currency: str
    status: str
    idempotency_key: str
    payment_token: str
    risk_score: Decimal | None
    risk_decision: str | None
    risk_processed_at: datetime | None
    created_at: datetime
    updated_at: datetime