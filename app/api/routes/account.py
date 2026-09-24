from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUserId, DBSession
from app.models import Account
from app.schemas.account import AccountResponse

router = APIRouter(
    prefix="/api/v1/account",
    tags=["Account"],
)


@router.get(
    "/me",
    response_model=AccountResponse,
)
def get_my_account(
    user_id: CurrentUserId,
    db: DBSession,
) -> AccountResponse:
    account = db.scalar(
        select(Account).where(
            Account.user_id == user_id,
        )
    )

    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found.",
        )

    return AccountResponse.model_validate(
        account,
        from_attributes=True,
    )
