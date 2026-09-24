"""add transaction created_at index

Revision ID: e69f7e117ac8
Revises: 60c606468c13
Create Date: 2026-09-24 16:56:08.477259

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "e69f7e117ac8"
down_revision = "60c606468c13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add an index for transaction time-range queries."""
    op.create_index(
        "ix_transactions_created_at",
        "transactions",
        ["created_at"],
    )


def downgrade() -> None:
    """Remove the transaction created_at index."""
    op.drop_index(
        "ix_transactions_created_at",
        table_name="transactions",
    )
