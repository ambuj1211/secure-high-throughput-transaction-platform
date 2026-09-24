from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import requests


@dataclass
class ApiClientError(Exception):
    message: str
    status_code: int | None = None
    detail: Any = None

    def __str__(self) -> str:
        return self.message


class ApiClient:
    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any = None,
        data: Any = None,
        params: dict[str, str] | None = None,
    ) -> tuple[int, Any]:
        try:
            response = requests.request(
                method,
                f"{self.base_url}{path}",
                headers=headers,
                json=json,
                data=data,
                params=params,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ApiClientError(
                f"Could not reach backend at {self.base_url}: {exc}"
            ) from exc

        try:
            body = response.json()
        except ValueError:
            body = response.text

        if response.status_code >= 400:
            detail = body.get("detail") if isinstance(body, dict) else body
            raise ApiClientError(
                f"HTTP {response.status_code}",
                status_code=response.status_code,
                detail=detail,
            )

        return response.status_code, body

    def login(self, email: str, password: str) -> dict[str, Any]:
        # Try JSON first.
        try:
            _, body = self._request(
                "POST",
                "/api/v1/auth/login",
                json={
                    "email": email,
                    "password": password,
                },
            )
            if isinstance(body, dict):
                return body
        except ApiClientError as exc:
            # 422 commonly means the endpoint expects form data.
            # Do not retry for authentication failures.
            if exc.status_code != 422:
                raise

        # Compatibility fallback for OAuth2-style form login.
        _, body = self._request(
            "POST",
            "/api/v1/auth/login",
            data={
                "username": email,
                "email": email,
                "password": password,
            },
        )

        if not isinstance(body, dict):
            raise ApiClientError("Unexpected login response.")

        return body

    def register(
        self,
        name: str,
        email: str,
        password: str,
    ) -> dict[str, Any]:
        _, body = self._request(
            "POST",
            "/api/v1/auth/register",
            json={
                "name": name,
                "email": email,
                "password": password,
            },
        )

        if not isinstance(body, dict):
            raise ApiClientError(
                "Unexpected registration response."
            )

        return body

    def get_me(self, token: str) -> dict[str, Any]:
        _, body = self._request(
            "GET",
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )

        if not isinstance(body, dict):
            raise ApiClientError("Unexpected /me response.")

        return body

    def health(self) -> dict[str, Any]:
        _, body = self._request("GET", "/health")

        if not isinstance(body, dict):
            raise ApiClientError("Unexpected health response.")

        return body

    def create_transaction(
        self,
        token: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> tuple[dict[str, Any], int]:
        status_code, body = self._request(
            "POST",
            "/api/v1/transactions",
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": idempotency_key,
            },
            json=payload,
        )

        if not isinstance(body, dict):
            body = {"response": body}

        return body, status_code

    @staticmethod
    def new_idempotency_key() -> str:
        return str(uuid4())

    @staticmethod
    def new_payment_token() -> str:
        return f"flask-demo-token-{uuid4()}"

