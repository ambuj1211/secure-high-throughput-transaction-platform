# Secure High-Throughput Transaction Processing Platform

A security-focused backend engineering project that simulates a high-throughput financial transaction workflow using synthetic users, accounts, merchants, transactions, and payment tokens.

The project is designed to demonstrate practical backend engineering across API development, database consistency, concurrency, security, background processing, analytics, automated testing, CI/CD, load testing, and observability.

> **Scope:** This is a portfolio/educational simulation. It does not process real money, store real card data, or claim PCI-DSS compliance or production payment-processing readiness.

## Tech Stack

| Area | Technology |
|---|---|
| Language | Python 3.12 |
| API | FastAPI |
| ORM / DB access | SQLAlchemy |
| Database | PostgreSQL |
| Migrations | Alembic |
| Rate limiting | Redis |
| Numerical processing | NumPy |
| Analytics | Pandas |
| Authentication | JWT, pwdlib/Argon2 |
| Testing | Pytest |
| Load testing | Locust |
| Containers | Docker / Docker Compose |
| CI | GitHub Actions |
| Metrics | Prometheus |
| Dashboards | Grafana |
| Static analysis | Ruff, Mypy |

## What the Project Implements

### Transaction API

The backend exposes a FastAPI transaction workflow with request validation, authenticated user context, idempotency protection, PostgreSQL persistence, and background risk processing.

### Authentication and Authorization

- JWT-based authentication
- Role-based authorization
- Database-backed user lookup where resource access requires it
- JWT-only user identity extraction on the transaction creation path to avoid an unnecessary user-table lookup per request
- Login rate limiting through Redis

### Transaction Safety

- Database-enforced unique idempotency keys
- PostgreSQL transactions for consistent state changes
- Concurrency control for account access
- Protection against duplicate transaction creation
- Authorization based on the authenticated JWT identity rather than a client-supplied user ID

### Risk Processing

A deterministic NumPy-based risk engine scores transactions on a `0–100` scale and maps the result to an action:

```text
score < 40    -> ALLOW
40 <= score < 70 -> REVIEW
score >= 70   -> BLOCK
```

Risk processing is handled through a database-backed `RiskJob` workflow. Multiple workers can safely claim pending jobs using row locking with `FOR UPDATE SKIP LOCKED`.

The risk engine is intentionally transparent and rule/statistical based; it is not presented as a trained fraud-detection ML model.

### Pandas Analytics

The analytics service converts transaction data into Pandas DataFrames and provides summary information such as:

- transaction counts
- status distributions
- risk-decision distributions
- aggregate transaction statistics
- optional time-window filtering

### Observability

The application exposes Prometheus-compatible metrics at:

```text
GET /metrics/
```

The Docker Compose monitoring stack includes Prometheus and Grafana. Grafana provisions a `Transaction Platform Overview` dashboard backed by Prometheus.

## Architecture

```text
                    Client
                      |
                      v
              +----------------+
              |    FastAPI     |
              +--------+-------+
                       |
          +------------+-------------+
          |            |             |
          v            v             v
       JWT/Auth      Redis       Transactions
          |         Rate Limit        |
          |                            v
          |                       PostgreSQL
          |                            |
          |                     +------+------+
          |                     |             |
          |                     v             v
          |                 Transactions   Risk Jobs
          |                                   |
          |                                   v
          |                           Concurrent Worker
          |                                   |
          |                                   v
          |                             NumPy Risk Engine
          |
          +------------------------------+
                                         |
                                    Pandas Analytics

           FastAPI Metrics
                 |
                 v
             Prometheus
                 |
                 v
              Grafana
```

See [Architecture.md](Architecture.md) for the detailed design.

## Main API Endpoints

```text
POST /api/v1/auth/login
GET  /api/v1/auth/me
POST /api/v1/transactions
GET  /health
GET  /metrics/
```

The exact request and response schemas are defined in the FastAPI application and Pydantic models.

## Security Controls

The implemented security scope includes:

- JWT authentication
- RBAC / role checks
- Redis-backed atomic login rate limiting
- database-enforced idempotency
- BOLA/IDOR protection
- Pydantic input validation
- SQLAlchemy parameterized database access
- synthetic payment tokens only
- environment-based secret configuration
- secure error handling and security-focused automated tests

The project deliberately does **not** claim to provide production-grade WAF, DDoS protection, PCI-DSS compliance, or real payment-card security.

## Database Design

The current relational model includes:

```text
users
merchants
accounts
transactions
risk_jobs
```

Important database properties include:

- UUID primary keys
- indexed and unique email fields where applicable
- foreign-key relationships
- monetary values stored using fixed-precision numeric types
- non-negative account balances
- unique idempotency keys
- transaction/risk-job relationships
- constraints for valid monetary and risk-score values

Alembic manages schema migrations.

## Redis Usage

Redis is used for short-lived application state, primarily for atomic login rate limiting.

The rate limiter uses an atomic Lua script to combine increment and expiration behavior, avoiding a race between separate `INCR` and `EXPIRE` operations.

Redis is not the source of truth for account balances or transaction state.

## Testing

The test suite covers the implemented backend behavior across:

```text
Unit tests
API tests
Authentication tests
Database integration tests
Security tests
Concurrency tests
Risk-worker tests
Analytics tests
```

### Latest verified test result

```text
42 passed
2 warnings
```

The two warnings are deprecation warnings from the test/dependency stack; they do not represent failing tests.

### Code quality

Verified locally:

```text
Ruff  -> All checks passed
Mypy  -> Success: no issues found in 27 source files
Pytest -> 42 passed
```

Database migration validation also passes:

```text
alembic current -> 48b98ec03172 (head)
alembic check   -> No new upgrade operations detected
```

## Load Testing

Locust is used to exercise the transaction creation endpoint with synthetic users and unique idempotency keys/payment tokens.

### Verified Docker benchmark

Configuration:

```text
Users:       100 concurrent users
Spawn rate:  10 users/second
Duration:    30 seconds
Endpoint:    POST /api/v1/transactions
```

Result:

| Metric | Result |
|---|---:|
| Requests | 3,196 |
| Failures | 0 |
| Error rate | 0.00% |
| Throughput | 108.76 req/s |
| P50 | 680 ms |
| P95 | 860 ms |
| P99 | 1,000 ms |
| Maximum | 1,200 ms |

These are local development-machine measurements, not a production capacity guarantee.

## Monitoring

The local observability stack is:

```text
FastAPI
  |
  +--> Prometheus metrics --> Prometheus --> Grafana
```

Verified components:

- Prometheus is scraping the FastAPI application's metrics endpoint.
- Grafana runs on version `13.2.2`.
- The `Transaction Platform Overview` dashboard is provisioned automatically.
- The Prometheus datasource is provisioned with UID `prometheus`.

Local URLs:

```text
FastAPI     http://127.0.0.1:8000
Prometheus  http://127.0.0.1:9090
Grafana     http://127.0.0.1:3000
```

## Docker Compose

The local Docker stack contains:

```text
transaction-app
transaction-postgres
transaction-redis
transaction-prometheus
transaction-grafana
```

Start the complete stack:

```powershell
docker compose up -d --build
```

Check container status:

```powershell
docker compose ps
```

Check the API:

```powershell
curl.exe http://127.0.0.1:8000/health
```

## Local Setup

1. Create the environment file from the template:

```powershell
Copy-Item .env.example .env
```

2. Set a strong `JWT_SECRET_KEY` in `.env`. Keep `.env` local and never commit it.

3. Start the stack:

```powershell
docker compose up -d --build
```

4. Verify the API:

```powershell
curl.exe http://127.0.0.1:8000/health
```

5. Run tests locally when the Python development environment is active:

```powershell
ruff check app tests
mypy app
pytest -q
```

## Load Test Example

With the Docker API running:

```powershell
locust -f .\locustfile.py --headless -u 100 -r 10 -t 30s --host http://127.0.0.1:8000
```

The Locust workload uses synthetic test accounts and generated idempotency/payment-token values.

## Project Structure

```text
app/
├── api/
│   ├── deps.py
│   └── routes/
├── core/
│   ├── config.py
│   ├── metrics.py
│   └── security.py
├── db/
│   ├── base.py
│   └── session.py
├── models/
│   └── entities.py
├── schemas/
│   ├── auth.py
│   └── transaction.py
├── services/
│   ├── rate_limiter.py
│   ├── risk_engine.py
│   ├── transaction_analytics.py
│   └── transaction_service.py
└── workers/
    └── risk_worker.py

tests/
├── api/
├── concurrency/
├── integration/
├── security/
├── unit/
├── workers/
└── test_health.py

monitoring/
├── prometheus.yml
└── grafana/
    ├── dashboards/
    └── provisioning/

Dockerfile
docker-compose.yml
locustfile.py
requirements.txt
pyproject.toml
Architecture.md
TestingList.md
Progress.md
```

## CI/CD

GitHub Actions runs the backend quality and test pipeline, including:

- dependency installation
- PostgreSQL and Redis services
- database migration setup
- Ruff checks
- Mypy checks
- Pytest

The CI workflow has been successfully verified on GitHub for the implemented backend and containerization changes.

## Engineering Principles

- PostgreSQL is the source of truth for financial state.
- Database constraints protect critical invariants.
- Idempotency is enforced at the database boundary.
- Protected resources derive user identity from authenticated credentials.
- Concurrency-sensitive state changes are handled transactionally.
- Background jobs are retryable and safe for concurrent claiming.
- Metrics and benchmark claims are based on actual execution.
- Secrets and real payment credentials are never committed.
- Complexity is added only where it demonstrates a meaningful engineering requirement.

## Known Scope and Limitations

This project is intentionally a backend engineering simulation. It does not implement or claim:

- real-money settlement
- real credit/debit card processing
- PCI-DSS certification or compliance
- production WAF/DDoS protection
- bank-grade fraud detection
- cloud production deployment
- production SLA or capacity guarantees
- a real external message broker
- production-scale distributed orchestration

The system is intended for local development, testing, benchmarking, and portfolio demonstration.

## Resume Positioning

**Secure High-Throughput Transaction Processing Platform**

Suggested technologies:

`Python, FastAPI, PostgreSQL, SQLAlchemy, Redis, NumPy, Pandas, Pytest, Locust, Docker, GitHub Actions, Prometheus, Grafana`

A concise project description for a resume:

> Built a security-focused transaction-processing backend with FastAPI, PostgreSQL, Redis, JWT/RBAC, database-enforced idempotency, concurrency-safe transaction handling, a NumPy-based risk engine, Pandas analytics, automated testing, Docker, GitHub Actions, Locust load testing, and Prometheus/Grafana observability.

## License

For portfolio/educational use. Add a project-specific open-source license before public distribution if required.
