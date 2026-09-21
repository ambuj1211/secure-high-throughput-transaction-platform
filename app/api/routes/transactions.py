from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status

from app.api.deps import CurrentUserId, DBSession
from app.schemas.transaction import TransactionCreate, TransactionResponse
from app.services.exceptions import (
    AccountNotFoundError,
    IdempotencyConflictError,
    InsufficientFundsError,
    MerchantNotFoundError,
)
from app.services.transaction_service import create_transaction

router = APIRouter(
    prefix="/api/v1/transactions",
    tags=["Transactions"],
)

IdempotencyHeader = Annotated[str, Header(alias="Idempotency-Key")]


@router.post(
    "",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_transaction_endpoint(
    request: TransactionCreate,
    idempotency_key: IdempotencyHeader,
    user_id: CurrentUserId,
    db: DBSession,
) -> TransactionResponse:
    if not idempotency_key.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key must not be empty.",
        )

    try:
        transaction = create_transaction(
            db=db,
            user_id=user_id,
            request=request,
            idempotency_key=idempotency_key,
        )

        return TransactionResponse.model_validate(transaction)


    except MerchantNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    except AccountNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    except InsufficientFundsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    except IdempotencyConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
