from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class RiskResult:
    score: float
    decision: str


def calculate_risk_score(
    amount: float,
    transactions_last_hour: int,
    account_age_days: int,
    is_new_merchant: bool,
) -> RiskResult:
    """
    Calculate a deterministic synthetic transaction risk score.

    Score range: 0-100.
    Higher score indicates more suspicious synthetic behavior.
    """

    features = np.array(
        [
            min(amount / 10000.0, 1.0),
            min(transactions_last_hour / 20.0, 1.0),
            max(0.0, 1.0 - min(account_age_days / 365.0, 1.0)),
            float(is_new_merchant),
        ],
        dtype=np.float64,
    )

    weights = np.array(
        [0.40, 0.30, 0.20, 0.10],
        dtype=np.float64,
    )

    score = float(np.dot(features, weights) * 100.0)
    score = float(np.clip(score, 0.0, 100.0))

    if score >= 70:
        decision = "BLOCK"
    elif score >= 40:
        decision = "REVIEW"
    else:
        decision = "ALLOW"

    return RiskResult(
        score=round(score, 2),
        decision=decision,
    )
