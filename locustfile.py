from __future__ import annotations

from uuid import uuid4

from locust import HttpUser, between, task

from app.core.security import create_access_token

LOAD_TEST_ACCOUNTS = [
    "9d57e070-2d26-44d1-b879-aea518f62dfa",
    "767322a8-eb70-40c1-b467-2565cbf3bdcd",
    "2ae4430b-1479-4497-9f52-2e680cf4e38b",
    "93ef602d-415d-496a-b3ed-8fd21b848bd4",
    "c627b4ba-92f8-4b13-a3fc-b70b828c4030",
    "1c3f5522-efe4-4901-8316-04eff1c29dc5",
    "b66b5aba-6627-4f63-9086-a4abd2f5c6a1",
    "0014c273-d288-4573-8662-a6f26b7b7aac",
    "a3f40a96-c672-4e02-9983-32a84e5787a2",
    "3250a847-1e14-4fff-b6b7-02724e408cb0",
    "794e7647-ed4f-41e0-adb0-69e460959a1f",
    "5dfb995a-677c-40a3-bd33-d3544f188772",
    "15f1c203-7f82-442b-a706-e02922f0f6a5",
    "e8b368d9-539e-4ccd-a325-49f359d65306",
    "c5ee87f3-2b52-4ee2-b0cc-a7233f7ccb21",
    "34fd307a-23c7-4005-b05c-99f127b0dcab",
    "8f83a1fe-3c56-4ff5-aea4-8f20b0c97e7a",
    "9e2e256c-7a52-4a40-bdae-dc75ed789da0",
    "8ec5edd5-7f5f-44de-b59a-e7c7085b2858",
    "85c6f3ba-675d-429a-abd9-9a56845e6723",
]

MERCHANT_ID = "4d320ba1-377a-4928-97e2-127faedcf9ec"


class TransactionUser(HttpUser):
    wait_time = between(0.10, 0.20)

    def on_start(self) -> None:
        if not hasattr(TransactionUser, "_next_account"):
            TransactionUser._next_account = 0
    
        self.user_index = TransactionUser._next_account
        TransactionUser._next_account += 1
    
        self.user_id = LOAD_TEST_ACCOUNTS[
            self.user_index % len(LOAD_TEST_ACCOUNTS)
        ]
    
        self.token = create_access_token(
            user_id=self.user_id,
            role="user",
        )

    @task
    def create_transaction(self) -> None:
        with self.client.post(
            "/api/v1/transactions",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Idempotency-Key": str(uuid4()),
            },
            json={
                "merchant_id": MERCHANT_ID,
                "amount": "0.01",
                "currency": "INR",
                "payment_token": f"locust-benchmark-{uuid4()}",
            },
            name="POST /api/v1/transactions",
            catch_response=True,
        ) as response:
            if response.status_code != 201:
                response.failure(
                    f"Expected 201, got {response.status_code}: "
                    f"{response.text[:200]}"
                )
