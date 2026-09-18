from app.services.risk_engine import calculate_risk_score


def test_low_risk_transaction_is_allowed():
    result = calculate_risk_score(
        amount=100.0,
        transactions_last_hour=1,
        account_age_days=365,
        is_new_merchant=False,
    )

    assert result.score < 40
    assert result.decision == "ALLOW"


def test_medium_risk_transaction_requires_review():
    result = calculate_risk_score(
        amount=5000.0,
        transactions_last_hour=8,
        account_age_days=90,
        is_new_merchant=True,
    )

    assert 40 <= result.score < 70
    assert result.decision == "REVIEW"


def test_high_risk_transaction_is_blocked():
    result = calculate_risk_score(
        amount=10000.0,
        transactions_last_hour=20,
        account_age_days=0,
        is_new_merchant=True,
    )

    assert result.score >= 70
    assert result.decision == "BLOCK"


def test_score_is_bounded():
    result = calculate_risk_score(
        amount=1000000.0,
        transactions_last_hour=1000,
        account_age_days=0,
        is_new_merchant=True,
    )

    assert 0 <= result.score <= 100
