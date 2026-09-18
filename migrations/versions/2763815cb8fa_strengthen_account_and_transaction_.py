"""strengthen account and transaction constraints

Revision ID: 2763815cb8fa
Revises: 3eea4bdb0a8a
Create Date: 2026-09-19 01:24:03.344569

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2763815cb8fa'
down_revision: Union[str, Sequence[str], None] = '3eea4bdb0a8a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add optimistic-concurrency fields to accounts.
    op.add_column(
        "accounts",
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    op.add_column(
        "accounts",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    # Make each user own at most one account.
    op.drop_index(
        op.f("ix_accounts_user_id"),
        table_name="accounts",
    )

    op.create_index(
        op.f("ix_accounts_user_id"),
        "accounts",
        ["user_id"],
        unique=True,
    )

    # Database-level financial invariants.
    op.create_check_constraint(
        "ck_accounts_balance_non_negative",
        "accounts",
        "balance >= 0",
    )

    op.create_check_constraint(
        "ck_transactions_amount_positive",
        "transactions",
        "amount > 0",
    )

    # Remove migration-time defaults after existing rows have been handled.
    op.alter_column(
        "accounts",
        "version",
        server_default=None,
    )

    op.alter_column(
        "accounts",
        "updated_at",
        server_default=None,
    )


def downgrade() -> None:
    """Downgrade schema."""

    op.drop_constraint(
        "ck_transactions_amount_positive",
        "transactions",
        type_="check",
    )

    op.drop_constraint(
        "ck_accounts_balance_non_negative",
        "accounts",
        type_="check",
    )

    op.drop_index(
        op.f("ix_accounts_user_id"),
        table_name="accounts",
    )

    op.create_index(
        op.f("ix_accounts_user_id"),
        "accounts",
        ["user_id"],
        unique=False,
    )

    op.drop_column("accounts", "updated_at")
    op.drop_column("accounts", "version")