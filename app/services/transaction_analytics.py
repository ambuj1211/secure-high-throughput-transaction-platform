from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Transaction


@dataclass(frozen=True)
class TransactionAnalytics:
    transaction_count: int
    total_amount: Decimal
    average_amount: Decimal
    status_counts: dict[str, int]
    risk_decision_counts: dict[str, int]


def calculate_transaction_analytics(
    transactions: list[dict[str, object]],
) -> TransactionAnalytics:
    """
    Calculate analytics from transaction records using Pandas.

    These metrics are analytical summaries only and are not used as the
    authoritative financial balance.
    """
    columns = [
        "amount",
        "currency",
        "status",
        "risk_decision",
        "created_at",
    ]

    if not transactions:
        return TransactionAnalytics(
            transaction_count=0,
            total_amount=Decimal("0.00"),
            average_amount=Decimal("0.00"),
            status_counts={},
            risk_decision_counts={},
        )

    df = pd.DataFrame(transactions)

    for column in columns:
        if column not in df.columns:
            df[column] = None

    df["amount"] = pd.to_numeric(
        df["amount"],
        errors="raise",
    )

    transaction_count = len(df)
    total_amount = Decimal(str(df["amount"].sum()))
    average_amount = Decimal(str(df["amount"].mean()))

    status_counts = df["status"].fillna("UNKNOWN").value_counts().astype(int).to_dict()

    risk_decision_counts = (
        df["risk_decision"].fillna("UNPROCESSED").value_counts().astype(int).to_dict()
    )

    return TransactionAnalytics(
        transaction_count=transaction_count,
        total_amount=total_amount.quantize(Decimal("0.01")),
        average_amount=average_amount.quantize(Decimal("0.01")),
        status_counts=status_counts,
        risk_decision_counts=risk_decision_counts,
    )


def generate_transaction_analytics(
    db: Session,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> TransactionAnalytics:
    """
    Query transactions from PostgreSQL and generate a Pandas-based report.
    """
    statement = select(
        Transaction.amount,
        Transaction.currency,
        Transaction.status,
        Transaction.risk_decision,
        Transaction.created_at,
    ).order_by(Transaction.created_at.asc())

    if start_at is not None:
        statement = statement.where(Transaction.created_at >= start_at)

    if end_at is not None:
        statement = statement.where(Transaction.created_at < end_at)

    rows = db.execute(statement).mappings().all()

    return calculate_transaction_analytics([dict(row) for row in rows])
