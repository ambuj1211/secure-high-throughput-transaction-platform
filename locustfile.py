from __future__ import annotations

import os
from uuid import uuid4

from locust import HttpUser, between, task

from app.core.security import create_access_token

LOAD_TEST_USER_IDS = [
    "20bc3fcd-f158-4ac6-8159-b40196b94fa8",
    "5a3192db-3667-461b-aabc-9805255f8305",
    "3ee8e2c6-786a-4ec9-a873-21e1630ecf80",
    "e70e8eec-ebce-4b1c-b583-998480254f6f",
    "de3cdbd1-0637-4f50-8e00-7c4784e8f52e",
    "85c6f3ba-675d-429a-abd9-9a56845e6723",
    "8ec5edd5-7f5f-44de-b59a-e7c7085b2858",
    "9e2e256c-7a52-4a40-bdae-dc75ed789da0",
    "8f83a1fe-3c56-4ff5-aea4-8f20b0c97e7a",
    "34fd307a-23c7-4005-b05c-99f127b0dcab",
    "c5ee87f3-2b52-4ee2-b0cc-a7233f7ccb21",
    "e8b368d9-539e-4ccd-a325-49f359d65306",
    "15f1c203-7f82-442b-a706-e02922f0f6a5",
    "5dfb995a-677c-40a3-bd33-d3544f188772",
    "794e7647-ed4f-41e0-adb0-69e460959a1f",
    "3250a847-1e14-4fff-b6b7-02724e408cb0",
    "a3f40a96-c672-4e02-9983-32a84e5787a2",
    "0014c273-d288-4573-8662-a6f26b7b7aac",
    "b66b5aba-6627-4f63-9086-a4abd2f5c6a1",
]

MERCHANT_ACCOUNT_ID = os.getenv(
    "LOAD_TEST_MERCHANT_ACCOUNT_ID",
    "47f5fb50-35ba-4ee8-8255-48163e24772d",
)

TRANSACTION_AMOUNT = os.getenv("LOAD_TEST_AMOUNT", "0.01")


class TransactionUser(HttpUser):
    wait_time = between(0.10, 0.20)

    _next_user_index = 0

    def on_start(self) -> None:
        self.user_index = TransactionUser._next_user_index
        TransactionUser._next_user_index += 1

        self.user_id = LOAD_TEST_USER_IDS[
            self.user_index % len(LOAD_TEST_USER_IDS)
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
                "transaction_type": "P2M",
                "receiver_account_id": MERCHANT_ACCOUNT_ID,
                "amount": TRANSACTION_AMOUNT,
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
