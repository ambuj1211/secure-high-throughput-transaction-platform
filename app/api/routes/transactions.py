from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status

from app.api.deps import CurrentUserId, DBSession
from app.schemas.transaction import TransactionCreate, TransactionResponse
from app.services.exceptions import (
    AccountNotFoundError,
    IdempotencyConflictError,
    InsufficientFundsError,
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

    # A normal participant must never choose an arbitrary sender account.
    # The sender is resolved from the authenticated JWT.
    if request.sender_account_id is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="sender_account_id must not be supplied for participant transfers.",
        )

    try:
        transaction = create_transaction(
            db=db,
            user_id=user_id,
            request=request,
            idempotency_key=idempotency_key,
            sender_account_id=None,
        )

        return TransactionResponse.model_validate(transaction)

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

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc