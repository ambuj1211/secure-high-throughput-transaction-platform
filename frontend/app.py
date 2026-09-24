from __future__ import annotations

import json
import os
import secrets
from collections.abc import Callable
from functools import wraps
from typing import Any

from api_client import ApiClient, ApiClientError
from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv(
    "FLASK_SECRET_KEY",
    secrets.token_hex(32),
)
app.config["FASTAPI_BASE_URL"] = os.getenv(
    "FASTAPI_BASE_URL",
    "http://127.0.0.1:8000",
).rstrip("/")
app.config["PROMETHEUS_BASE_URL"] = os.getenv(
    "PROMETHEUS_BASE_URL",
    "http://127.0.0.1:9090",
).rstrip("/")
app.config["DEMO_MERCHANT_ID"] = os.getenv(
    "DEMO_MERCHANT_ID",
    "4d320ba1-377a-4928-97e2-127faedcf9ec",
)
app.config["REQUEST_TIMEOUT"] = float(
    os.getenv("REQUEST_TIMEOUT", "5")
)


api = ApiClient(
    app.config["FASTAPI_BASE_URL"],
    app.config["REQUEST_TIMEOUT"],
)

prometheus = ApiClient(
    app.config["PROMETHEUS_BASE_URL"],
    app.config["REQUEST_TIMEOUT"],
)


def error_text(exc: ApiClientError) -> str:
    if isinstance(exc.detail, dict):
        detail = exc.detail.get("detail", exc.detail)
        if isinstance(detail, (dict, list)):
            return json.dumps(detail)
        return str(detail)

    if isinstance(exc.detail, list):
        return json.dumps(exc.detail)

    return str(exc.detail or exc.message)


def prometheus_query(query: str) -> float | None:
    try:
        response = prometheus._request(
            "GET",
            "/api/v1/query",
            params={"query": query},
        )[1]
    except ApiClientError:
        return None

    results = response.get("data", {}).get("result", [])

    if not results:
        return None

    try:
        return float(results[0]["value"][1])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def get_metrics() -> dict[str, Any]:
    transaction_path = "/api/v1/transactions"

    return {
        "request_rate": prometheus_query(
            'sum(rate(http_requests_total{job="transaction-app"}[1m]))'
        ),
        "transaction_rate": prometheus_query(
            f'sum(rate(http_requests_total{{'
            f'job="transaction-app",'
            f'path="{transaction_path}"'
            f'}}[1m]))'
        ),
        "error_rate": prometheus_query(
            'sum(rate(http_requests_total{job="transaction-app",status=~"5.."}[1m]))'
        ),
        "transaction_p95": prometheus_query(
            f'histogram_quantile(0.95,'
            f' sum(rate(http_request_duration_seconds_bucket{{'
            f'job="transaction-app",'
            f'path="{transaction_path}"'
            f'}}[1m])) by (le))'
        ),
    }


@app.template_filter("pretty_json")
def pretty_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True)


@app.template_filter("number")
def number(value: float | int | None) -> str:
    if value is None:
        return "—"

    return f"{value:,.2f}"


@app.template_filter("milliseconds")
def milliseconds(value: float | None) -> str:
    if value is None:
        return "—"

    return f"{value * 1000:.0f} ms"


@app.context_processor
def layout_context() -> dict[str, Any]:
    return {
        "current_user": session.get("user"),
        "authenticated": bool(session.get("access_token")),
    }


def login_required(
    view: Callable[..., Any],
) -> Callable[..., Any]:

    @wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if not session.get("access_token"):
            flash(
                "Sign in to access the transaction console.",
                "error",
            )
            return redirect(url_for("login"))

        return view(*args, **kwargs)

    return wrapped


@app.get("/")
def index() -> Any:
    if session.get("access_token"):
        return redirect(url_for("dashboard"))

    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login() -> Any:
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not email or not password:
            flash(
                "Email and password are required.",
                "error",
            )
            return render_template(
                "login.html",
                email=email,
            )

        try:
            response = api.login(
                email=email,
                password=password,
            )

            access_token = response.get("access_token")

            if not access_token:
                raise ApiClientError(
                    "Backend login response did not contain access_token."
                )

            session.clear()
            session["access_token"] = access_token

            try:
                session["user"] = api.get_me(access_token)
            except ApiClientError:
                session["user"] = {"email": email}

            flash(
                "Authenticated successfully.",
                "success",
            )

            return redirect(url_for("dashboard"))

        except ApiClientError as exc:
            flash(
                f"Login failed: {error_text(exc)}",
                "error",
            )

    return render_template(
        "login.html",
        email=request.form.get(
            "email",
            request.args.get("email", ""),
        ),
    )


@app.route("/register", methods=["GET", "POST"])
def register() -> Any:
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get(
            "confirm_password",
            "",
        )

        if not name:
            flash(
                "Name is required.",
                "error",
            )

            return render_template(
                "register.html",
                name=name,
                email=email,
            )

        if not email:
            flash(
                "Email is required.",
                "error",
            )

            return render_template(
                "register.html",
                name=name,
                email=email,
            )

        if not password:
            flash(
                "Password is required.",
                "error",
            )

            return render_template(
                "register.html",
                name=name,
                email=email,
            )

        if password != confirm_password:
            flash(
                "Passwords do not match.",
                "error",
            )

            return render_template(
                "register.html",
                name=name,
                email=email,
            )

        try:
            api.register(
                name=name,
                email=email,
                password=password,
            )

            flash(
                "Account created successfully. Sign in to continue.",
                "success",
            )

            return redirect(
                url_for(
                    "login",
                    email=email,
                )
            )

        except ApiClientError as exc:
            flash(
                f"Registration failed: {error_text(exc)}",
                "error",
            )

    return render_template(
        "register.html",
        name=request.form.get("name", ""),
        email=request.form.get("email", ""),
    )

@app.post("/logout")
def logout() -> Any:
    session.clear()
    flash("Signed out.", "success")
    return redirect(url_for("login"))


@app.get("/dashboard")
@login_required
def dashboard() -> Any:
    try:
        health = api.health()
        api_healthy = health.get("status") == "ok"
    except ApiClientError:
        health = {"status": "unreachable"}
        api_healthy = False

    metrics = get_metrics()

    return render_template(
        "dashboard.html",
        health=health,
        api_healthy=api_healthy,
        metrics=metrics,
    )


@app.post("/dashboard/refresh")
@login_required
def dashboard_refresh() -> Any:
    try:
        health = api.health()
        api_healthy = health.get("status") == "ok"
    except ApiClientError:
        health = {"status": "unreachable"}
        api_healthy = False

    metrics = get_metrics()

    return jsonify(
        {
            "api_healthy": api_healthy,
            "health": health,
            "metrics": metrics,
        }
    )


@app.route("/transactions", methods=["GET", "POST"])
@login_required
def transactions() -> Any:
    result: dict[str, Any] | None = None
    status_code: int | None = None
    error: str | None = None

    last_request = session.get(
        "last_transaction_request"
    )

    if request.method == "POST":
        action = request.form.get(
            "action",
            "create",
        )

        if action == "replay":
            if not last_request:
                error = "No previous transaction exists to replay."
            else:
                payload = last_request["payload"]
                idempotency_key = last_request["idempotency_key"]

        else:
            idempotency_key = (
                request.form.get(
                    "idempotency_key",
                    "",
                ).strip()
                or api.new_idempotency_key()
            )

            payload = {
                "merchant_id": request.form.get(
                    "merchant_id",
                    app.config["DEMO_MERCHANT_ID"],
                ).strip(),
                "amount": request.form.get(
                    "amount",
                    "0.01",
                ).strip(),
                "currency": request.form.get(
                    "currency",
                    "INR",
                ).strip().upper(),
                "payment_token": (
                    request.form.get(
                        "payment_token",
                        "",
                    ).strip()
                    or api.new_payment_token()
                ),
            }

        if error is None:
            try:
                response, status_code = api.create_transaction(
                    session["access_token"],
                    payload,
                    idempotency_key,
                )

                result = response

                session["last_transaction_request"] = {
                    "payload": payload,
                    "idempotency_key": idempotency_key,
                }

                if status_code in (200, 201):
                    flash(
                        "Transaction request completed successfully.",
                        "success",
                    )

            except ApiClientError as exc:
                status_code = exc.status_code
                error = error_text(exc)

                flash(
                    "The backend rejected the transaction request.",
                    "error",
                )

    return render_template(
        "transactions.html",
        result=result,
        error=error,
        status_code=status_code,
        last_request=session.get(
            "last_transaction_request"
        ),
        demo_merchant_id=app.config[
            "DEMO_MERCHANT_ID"
        ],
    )


@app.route("/security", methods=["GET", "POST"])
@login_required
def security() -> Any:
    test_result: dict[str, Any] | None = None

    if request.method == "POST":
        action = request.form.get("action")

        if action == "invalid_jwt":
            try:
                body = api.get_me("definitely-invalid-token")

                test_result = {
                    "passed": False,
                    "status": 200,
                    "body": body,
                }

            except ApiClientError as exc:
                test_result = {
                    "passed": exc.status_code in (401, 403),
                    "status": exc.status_code,
                    "body": exc.detail,
                }

    return render_template(
        "security.html",
        test_result=test_result,
    )


@app.get("/observability")
@login_required
def observability() -> Any:
    return render_template(
        "observability.html",
        metrics=get_metrics(),
    )


@app.errorhandler(404)
def not_found(_error: Any) -> tuple[str, int]:
    return render_template("404.html"), 404


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
    )

