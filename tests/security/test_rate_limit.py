from uuid import uuid4

from app.core.config import settings
from app.services.rate_limiter import RateLimiter


def test_login_rate_limit(client):
    email = f"rate-limit-{uuid4()}@test.local"

    register_response = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Rate Limit User",
            "email": email,
            "password": "StrongPass123",
        },
    )

    assert register_response.status_code == 201

    limiter = RateLimiter(settings.redis_url)

    # Remove any previous local test state.
    limiter.redis.delete("rate-limit:login:testclient")

    responses = []

    for _ in range(6):
        responses.append(
            client.post(
                "/api/v1/auth/login",
                json={
                    "email": email,
                    "password": "WrongPass123",
                },
            )
        )

    assert [response.status_code for response in responses[:5]] == [
        401,
        401,
        401,
        401,
        401,
    ]

    assert responses[5].status_code == 429

    limiter.redis.delete("rate-limit:login:testclient")
