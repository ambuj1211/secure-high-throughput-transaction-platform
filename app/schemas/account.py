from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class AccountResponse(BaseModel):
    id: UUID
    user_id: UUID
    balance: Decimal
    currency: str
    version: int
