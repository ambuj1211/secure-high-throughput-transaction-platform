"""remove redundant idempotency index

Revision ID: 48b98ec03172
Revises: 85868466cf2f
Create Date: 2026-09-20 11:12:35.048876

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "48b98ec03172"
down_revision: Union[str, Sequence[str], None] = "85868466cf2f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index(
        "ix_transactions_idempotency_key",
        table_name="transactions",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.create_index(
        "ix_transactions_idempotency_key",
        "transactions",
        ["idempotency_key"],
        unique=True,
    )