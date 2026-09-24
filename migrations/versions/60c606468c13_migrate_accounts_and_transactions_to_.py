"""migrate accounts and transactions to transfer model

Revision ID: 60c606468c13
Revises: 40a2f662c984
Create Date: 2026-09-23 16:53:04.197395
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "60c606468c13"
down_revision: str | Sequence[str] | None = "40a2f662c984"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()

    # ---------------------------------------------------------
    # 1. Allow accounts to belong to either a User or Merchant.
    # ---------------------------------------------------------
    op.alter_column(
        "accounts",
        "user_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )

    op.add_column(
        "accounts",
        sa.Column("merchant_id", sa.Uuid(), nullable=True),
    )

    op.create_foreign_key(
        "accounts_merchant_id_fkey",
        "accounts",
        "merchants",
        ["merchant_id"],
        ["id"],
    )

    op.create_index(
        "ix_accounts_merchant_id",
        "accounts",
        ["merchant_id"],
        unique=True,
    )

    # ---------------------------------------------------------
    # 2. Create one account for every existing merchant.
    #
    # Historical merchant balances are intentionally initialized
    # to zero. We must not replay old transactions.
    # ---------------------------------------------------------
    merchants = connection.execute(
        sa.text(
            """
            SELECT
                m.id,
                m.created_at
            FROM merchants m
            LEFT JOIN accounts a
                ON a.merchant_id = m.id
            WHERE a.id IS NULL
            """
        )
    ).mappings().all()

    for merchant in merchants:
        connection.execute(
            sa.text(
                """
                INSERT INTO accounts (
                    id,
                    merchant_id,
                    balance,
                    currency,
                    version,
                    created_at,
                    updated_at
                )
                VALUES (
                    :id,
                    :merchant_id,
                    0.00,
                    'INR',
                    0,
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "id": str(__import__("uuid").uuid4()),
                "merchant_id": merchant["id"],
                "created_at": merchant["created_at"],
                "updated_at": merchant["created_at"],
            },
        )

    # ---------------------------------------------------------
    # 3. Add generic transfer fields to transactions.
    # ---------------------------------------------------------
    op.add_column(
        "transactions",
        sa.Column(
            "transaction_type",
            sa.String(length=3),
            nullable=True,
        ),
    )

    op.add_column(
        "transactions",
        sa.Column(
            "sender_account_id",
            sa.Uuid(),
            nullable=True,
        ),
    )

    op.add_column(
        "transactions",
        sa.Column(
            "receiver_account_id",
            sa.Uuid(),
            nullable=True,
        ),
    )

    # ---------------------------------------------------------
    # 4. Backfill historical transactions.
    #
    # Old model:
    #   transactions.user_id     -> sender user
    #   transactions.merchant_id -> receiver merchant
    #
    # New model:
    #   sender_account_id        -> user's account
    #   receiver_account_id      -> merchant's account
    #
    # Therefore all historical records become P2M.
    # ---------------------------------------------------------
    connection.execute(
        sa.text(
            """
            UPDATE transactions AS t
            SET
                transaction_type = 'P2M',
                sender_account_id = sender.id,
                receiver_account_id = receiver.id
            FROM accounts AS sender,
                 accounts AS receiver
            WHERE sender.user_id = t.user_id
              AND receiver.merchant_id = t.merchant_id
            """
        )
    )

    # ---------------------------------------------------------
    # 5. Verify the complete backfill before making columns
    #    mandatory.
    # ---------------------------------------------------------
    missing_sender = connection.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM transactions
            WHERE sender_account_id IS NULL
            """
        )
    ).scalar_one()

    missing_receiver = connection.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM transactions
            WHERE receiver_account_id IS NULL
            """
        )
    ).scalar_one()

    missing_type = connection.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM transactions
            WHERE transaction_type IS NULL
            """
        )
    ).scalar_one()

    if missing_sender != 0:
        raise RuntimeError(
            f"Transaction backfill failed: "
            f"{missing_sender} rows have no sender account."
        )

    if missing_receiver != 0:
        raise RuntimeError(
            f"Transaction backfill failed: "
            f"{missing_receiver} rows have no receiver account."
        )

    if missing_type != 0:
        raise RuntimeError(
            f"Transaction backfill failed: "
            f"{missing_type} rows have no transaction type."
        )

    # ---------------------------------------------------------
    # 6. New fields can now become NOT NULL.
    # ---------------------------------------------------------
    op.alter_column(
        "transactions",
        "transaction_type",
        existing_type=sa.String(length=3),
        nullable=False,
    )

    op.alter_column(
        "transactions",
        "sender_account_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )

    op.alter_column(
        "transactions",
        "receiver_account_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )

    # ---------------------------------------------------------
    # 7. Add foreign keys.
    # ---------------------------------------------------------
    op.create_foreign_key(
        "transactions_sender_account_id_fkey",
        "transactions",
        "accounts",
        ["sender_account_id"],
        ["id"],
    )

    op.create_foreign_key(
        "transactions_receiver_account_id_fkey",
        "transactions",
        "accounts",
        ["receiver_account_id"],
        ["id"],
    )

    # ---------------------------------------------------------
    # 8. Add indexes.
    # ---------------------------------------------------------
    op.create_index(
        "ix_transactions_transaction_type",
        "transactions",
        ["transaction_type"],
        unique=False,
    )

    op.create_index(
        "ix_transactions_sender_account_id",
        "transactions",
        ["sender_account_id"],
        unique=False,
    )

    op.create_index(
        "ix_transactions_receiver_account_id",
        "transactions",
        ["receiver_account_id"],
        unique=False,
    )

    # ---------------------------------------------------------
    # 9. Add transfer constraints.
    # ---------------------------------------------------------
    op.create_check_constraint(
        "ck_transactions_type",
        "transactions",
        "transaction_type IN ('P2P', 'P2M', 'M2M', 'M2P')",
    )

    op.create_check_constraint(
        "ck_transactions_distinct_accounts",
        "transactions",
        "sender_account_id <> receiver_account_id",
    )

    # ---------------------------------------------------------
    # 10. Remove legacy transaction ownership columns.
    # ---------------------------------------------------------
    op.drop_constraint(
        "transactions_user_id_fkey",
        "transactions",
        type_="foreignkey",
    )

    op.drop_constraint(
        "transactions_merchant_id_fkey",
        "transactions",
        type_="foreignkey",
    )

    op.drop_index(
        "ix_transactions_user_id",
        table_name="transactions",
    )

    op.drop_index(
        "ix_transactions_merchant_id",
        table_name="transactions",
    )

    op.drop_column(
        "transactions",
        "user_id",
    )

    op.drop_column(
        "transactions",
        "merchant_id",
    )


def downgrade() -> None:
    connection = op.get_bind()

    # ---------------------------------------------------------
    # Generic transfer records cannot safely be converted back
    # to the original user -> merchant representation.
    # ---------------------------------------------------------
    non_p2m = connection.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM transactions
            WHERE transaction_type <> 'P2M'
            """
        )
    ).scalar_one()

    if non_p2m:
        raise RuntimeError(
            "Cannot downgrade because P2P, M2M, or M2P "
            "transactions exist."
        )

    # ---------------------------------------------------------
    # Restore legacy transaction columns.
    # ---------------------------------------------------------
    op.add_column(
        "transactions",
        sa.Column("user_id", sa.Uuid(), nullable=True),
    )

    op.add_column(
        "transactions",
        sa.Column("merchant_id", sa.Uuid(), nullable=True),
    )

    connection.execute(
        sa.text(
            """
            UPDATE transactions AS t
            SET
                transaction_type = 'P2M',
                sender_account_id = sender.id,
                receiver_account_id = receiver.id
            FROM accounts AS sender,
                 accounts AS receiver
            WHERE sender.user_id = t.user_id
              AND receiver.merchant_id = t.merchant_id
            """
        )
    )

    missing_legacy = connection.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM transactions
            WHERE user_id IS NULL
               OR merchant_id IS NULL
            """
        )
    ).scalar_one()

    if missing_legacy:
        raise RuntimeError(
            f"Cannot downgrade: {missing_legacy} transactions "
            "cannot be mapped back to the legacy schema."
        )

    op.alter_column(
        "transactions",
        "user_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )

    op.alter_column(
        "transactions",
        "merchant_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )

    op.create_foreign_key(
        "transactions_user_id_fkey",
        "transactions",
        "users",
        ["user_id"],
        ["id"],
    )

    op.create_foreign_key(
        "transactions_merchant_id_fkey",
        "transactions",
        "merchants",
        ["merchant_id"],
        ["id"],
    )

    op.create_index(
        "ix_transactions_user_id",
        "transactions",
        ["user_id"],
        unique=False,
    )

    op.create_index(
        "ix_transactions_merchant_id",
        "transactions",
        ["merchant_id"],
        unique=False,
    )

    # ---------------------------------------------------------
    # Remove new transaction fields.
    # ---------------------------------------------------------
    op.drop_constraint(
        "ck_transactions_distinct_accounts",
        "transactions",
        type_="check",
    )

    op.drop_constraint(
        "ck_transactions_type",
        "transactions",
        type_="check",
    )

    op.drop_index(
        "ix_transactions_receiver_account_id",
        table_name="transactions",
    )

    op.drop_index(
        "ix_transactions_sender_account_id",
        table_name="transactions",
    )

    op.drop_index(
        "ix_transactions_transaction_type",
        table_name="transactions",
    )

    op.drop_constraint(
        "transactions_receiver_account_id_fkey",
        "transactions",
        type_="foreignkey",
    )

    op.drop_constraint(
        "transactions_sender_account_id_fkey",
        "transactions",
        type_="foreignkey",
    )

    op.drop_column(
        "transactions",
        "receiver_account_id",
    )

    op.drop_column(
        "transactions",
        "sender_account_id",
    )

    op.drop_column(
        "transactions",
        "transaction_type",
    )

    # ---------------------------------------------------------
    # Remove merchant accounts.
    # ---------------------------------------------------------
    merchant_cash_ops = connection.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM cash_operations c
            JOIN accounts a
                ON a.id = c.account_id
            WHERE a.merchant_id IS NOT NULL
            """
        )
    ).scalar_one()

    if merchant_cash_ops:
        raise RuntimeError(
            "Cannot downgrade because merchant accounts "
            "are referenced by cash_operations."
        )

    op.drop_index(
        "ix_accounts_merchant_id",
        table_name="accounts",
    )

    op.drop_constraint(
        "accounts_merchant_id_fkey",
        "accounts",
        type_="foreignkey",
    )

    connection.execute(
        sa.text(
            """
            DELETE FROM accounts
            WHERE merchant_id IS NOT NULL
            """
        )
    )

    op.drop_column(
        "accounts",
        "merchant_id",
    )

    op.alter_column(
        "accounts",
        "user_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
