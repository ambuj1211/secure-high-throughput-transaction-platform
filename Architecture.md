# Architecture

## 1. System Overview

**Secure High-Throughput Transaction Processing Platform** is a single-user, local-first backend simulation built to demonstrate practical backend engineering around transaction processing, security, concurrency, risk processing, analytics, testing, and observability.

The implementation uses synthetic users, merchants, accounts, transactions, and payment tokens. It does not process real money, store real card numbers, or claim PCI-DSS or production-payment compliance.

The architecture is intentionally limited to components that are implemented in the repository. There is no external API gateway, WAF, Kafka/RabbitMQ queue, or outbox service in the current implementation.

## 2. Implemented High-Level Architecture

```text
                         Client / Locust
                                |
                                v
                    +-------------------------+
                    |      FastAPI App        |
                    |-------------------------|
                    | JWT Authentication       |
                    | RBAC / Authorization     |
                    | Request Validation       |
                    | Transaction API          |
                    | Performance Middleware   |
                    +-----------+-------------+
                                |
              +-----------------+------------------+
              |                                    |
              v                                    v
      +---------------+                    +---------------+
      |    Redis      |                    |  PostgreSQL   |
      |---------------|                    |---------------|
      | Login rate    |                    | Users         |
      | limiting      |                    | Merchants     |
      | velocity/state|                    | Accounts      |
      +---------------+                    | Transactions  |
                                           | Risk Jobs     |
                                           +-------+-------+
                                                   |
                                                   v
                                         +------------------+
                                         | Concurrent Risk  |
                                         | Worker           |
                                         +--------+---------+
                                                  |
                                                  v
                                         +------------------+
                                         | NumPy Risk Engine|
                                         +------------------+

                  Transaction Data
                         |
                         v
                 +---------------+
                 | Pandas         |
                 | Analytics      |
                 +---------------+

                    FastAPI Metrics
                         |
                         v
                   +-----------+
                   | Prometheus|
                   +-----+-----+
                         |
                         v
                    +---------+
                    | Grafana |
                    +---------+
```

## 3. Request and Transaction Flow

The implemented transaction path is designed to keep authentication lightweight while preserving database correctness for financial state changes.

```text
Client
  |
  | POST /api/v1/transactions
  v
JWT validation
  |
  v
Authenticated user ID from token
  |
  v
Pydantic request validation
  |
  v
Idempotency lookup
  |
  +---- existing key ----> return existing transaction/result
  |
  +---- new key ---------> continue
                           |
                           v
                    PostgreSQL transaction
                           |
                           +--> lock account row
                           |
                           +--> validate/update account state
                           |
                           +--> create transaction
                           |
                           +--> create risk job
                           |
                           v
                         COMMIT
                           |
                           v
                     HTTP response

Risk job processing is handled separately by the database-backed worker.
```

The current transaction endpoint uses a JWT-derived user ID instead of accepting the user identity from the request body. This prevents a caller from changing the owner of a transaction by submitting another user's ID.

## 4. Application Layers

### API layer

FastAPI routes expose the HTTP interface and handle authentication dependencies, request validation, and HTTP responses.

Current application capabilities include:

- authentication/login
- authenticated user access
- transaction creation
- health checking
- Prometheus-compatible metrics

### Service layer

Business logic is separated from route handlers. The transaction service coordinates idempotency checks, account locking, transaction creation, risk-job creation, and database commit handling.

The risk engine and analytics processing are also implemented as separate services.

### Data-access layer

SQLAlchemy provides the database session and ORM mappings. Alembic manages schema migrations.

## 5. Authentication and Authorization

Authentication uses signed JWT access tokens.

```text
Login request
     |
     v
Credential verification
     |
     v
JWT creation
     |
     v
Bearer token
     |
     v
Protected API
     |
     v
JWT validation
     |
     +--> user ID
     +--> role
```

Two authentication paths are used for different purposes:

- A database-backed authenticated-user dependency is used when the request needs user data or role information.
- The transaction path uses a JWT-only dependency that validates the token and extracts the UUID user ID without an additional user lookup for every transaction request.

Role information is used for authorization/RBAC checks on protected operations.

The login endpoint is protected by an atomic Redis rate limiter to reduce repeated authentication attempts.

## 6. Redis Rate Limiting

Redis is used for short-lived control state rather than as the source of truth for financial balances.

The login rate limiter uses a Redis Lua script so the increment and expiration are performed atomically.

```text
Request
  |
  v
Redis key for client
  |
  v
Atomic INCR + EXPIRE
  |
  +---- under limit ----> process request
  |
  +---- over limit -----> HTTP 429
```

The configured login limit in the current application is 5 requests per 60 seconds per client host.

## 7. Database Architecture

PostgreSQL is the authoritative store for users, merchants, accounts, transactions, and risk-job state.

### Users

```text
id              UUID primary key
email            unique/indexed email
password_hash   optional hashed password
role            user role
```



### Merchants

```text
id
email
```

Merchant email is unique and indexed.

### Accounts

```text
id
user_id
balance
currency
version
created_at
updated_at
```

Important invariants include a unique user-to-account relationship and a non-negative balance constraint.

### Transactions

```text
id
user_id
merchant_id
amount
currency
status
idempotency_key
payment_token
created_at
updated_at
risk_score
risk_decision
risk_processed_at
```

Important constraints include:

- primary-key identity using UUIDs
- foreign-key relationships to user and merchant
- positive transaction amount
- unique idempotency key
- risk score bounded to the configured 0-100 range

### Risk Jobs

```text
id
transaction_id
status
attempts
available_at
last_error
created_at
updated_at
```

Each transaction has at most one risk job. The job keeps retry/availability state independently from the transaction record.

## 8. Idempotency

Idempotency prevents a retried transaction request from creating a second logical transaction.

```text
Request + Idempotency-Key
          |
          v
Application lookup
          |
     +----+----+
     |         |
 existing     absent
     |         |
     v         v
return      create transaction
previous        |
result          v
          database unique constraint
```

The application performs an early lookup for the common duplicate case, while PostgreSQL enforces uniqueness at the database boundary. This protects the system when concurrent requests race on the same key.

## 9. Concurrency and Double-Spend Protection

Account state is protected using a PostgreSQL row lock during the transaction flow.

```text
BEGIN
  |
  v
SELECT account FOR UPDATE
  |
  v
Check available balance
  |
  +---- insufficient ----> rollback
  |
  +---- sufficient ------> update account
                              |
                              v
                         create transaction
                              |
                              v
                            COMMIT
```

The row-level lock serializes competing updates to the same account so two concurrent withdrawals cannot both consume the same available balance based on stale state.

Concurrency tests exercise this behavior.

## 10. Risk Engine

The current risk engine is a deterministic NumPy-based heuristic, not a trained machine-learning model.

The engine combines normalized risk features using fixed weights:

```text
weights = [0.40, 0.30, 0.20, 0.10]
```

The resulting score is mapped to a 0-100 range and classified as:

```text
risk_score < 40    -> ALLOW
40 <= score < 70   -> REVIEW
score >= 70        -> BLOCK
```

This design is intentionally transparent and reproducible, which makes it suitable for automated testing and debugging.

## 11. Concurrent Risk Worker

Risk processing is decoupled from the main transaction request by a PostgreSQL-backed `RiskJob` record.

The worker selects pending/available jobs using row-level locking with `FOR UPDATE SKIP LOCKED`.

```text
Risk Jobs
   |
   v
SELECT pending jobs
FOR UPDATE SKIP LOCKED
   |
   v
Increment attempts
   |
   v
NumPy risk calculation
   |
   +---- success ----> persist score/decision
   |
   +---- retry ------> update availability/error
   |
   +---- failure ----> persist failed state/error
```

`SKIP LOCKED` allows multiple workers to process different jobs without waiting on rows already claimed by another worker.

## 12. Pandas Analytics

Pandas is used for transaction analytics rather than for request-path persistence.

The analytics service builds a DataFrame from transaction records and performs operations such as:

- numeric conversion and normalization
- transaction counts
- status distributions
- risk-decision distributions
- aggregate transaction statistics
- optional time-window filtering

The service handles empty datasets explicitly so analytics calls do not fail simply because no transactions match the requested range.

## 13. Observability

The application exposes Prometheus-compatible metrics through `/metrics/`.

```text
FastAPI
  |
  +--> request counter
  |
  +--> request latency histogram
  |
  v
Prometheus
  |
  v
Grafana
```

Current application metrics include:

```text
http_requests_total
http_request_duration_seconds
```

The request counter is labeled by HTTP method, request path, and response status. The latency histogram is labeled by method and path and provides bucket data for percentile calculations in Prometheus/Grafana.

The current Docker Compose observability stack uses:

```text
Prometheus -> port 9090
Grafana    -> port 3000
```

Grafana is provisioned with the Prometheus datasource and the `Transaction Platform Overview` dashboard.

## 14. Performance and Load Testing

Locust is used to generate concurrent synthetic transaction traffic.

The current benchmark flow is:

```text
Locust users
    |
    v
JWT-authenticated transaction requests
    |
    v
FastAPI
    |
    +--> Redis
    +--> PostgreSQL
    +--> RiskJob creation
    |
    v
Prometheus metrics
```

A verified local Docker benchmark used 100 concurrent users for 30 seconds and produced:

```text
Requests:    3,196
Failures:    0
Throughput:  108.76 req/s
P50:         680 ms
P95:         860 ms
P99:         1,000 ms
Max:         1,200 ms
```

These figures are local development measurements, not production capacity guarantees.

## 15. Testing Architecture

The test suite is organized by behavior and integration boundary.

```text
Unit
 |-- risk engine
 |-- analytics

API
 |-- authentication
 |-- transactions

Security
 |-- BOLA/IDOR
 |-- rate limiting

Concurrency
 |-- transaction concurrency

Integration
 |-- database
 |-- transaction analytics + DB

Workers
 |-- risk worker

Health / regression
 |-- health endpoint
```

The latest verified local test run passed 42 tests, with two dependency deprecation warnings.

Static quality checks include Ruff and Mypy.

The GitHub Actions workflow also provisions PostgreSQL and Redis, applies Alembic migrations, runs lint/type checks, and executes the test suite.

## 16. Docker Deployment

The local deployment is defined by Docker Compose.

```text
transaction-app
transaction-postgres
transaction-redis
transaction-prometheus
transaction-grafana
```

The application container runs Alembic migrations before starting Uvicorn.

Environment configuration is provided through Docker Compose and `.env`; the JWT secret is required through the Compose variable `${JWT_SECRET_KEY:?JWT_SECRET_KEY must be set}` rather than being hard-coded in the Compose file.

## 17. Migrations

Alembic controls the PostgreSQL schema lifecycle.

The current migration chain includes changes for:

- initial schema
- strengthened constraints/indexes
- authentication fields
- risk-processing fields
- removal of a redundant idempotency index

The repository is expected to remain at the migration head, and `alembic check` is used to detect model/schema drift.

## 18. Design Principles

1. PostgreSQL is the source of truth for financial state.
2. Authorization is based on the authenticated identity, not a client-supplied owner ID.
3. Database constraints protect invariants that application-only checks cannot guarantee.
4. Idempotency is enforced at the database boundary.
5. Account updates use transactional row locking for concurrency correctness.
6. Redis is used for transient control state such as rate limiting, not as the balance store.
7. Risk processing is retryable and isolated from the synchronous transaction request.
8. Observability is built into the HTTP layer through Prometheus metrics.
9. Performance claims are documented only from executed benchmarks.
10. Only synthetic payment data is used.

## 19. Current Scope and Limitations

The current implementation is intentionally a portfolio-scale backend simulation.

It does not implement or claim:

- real payment settlement
- real card-number storage or processing
- PCI-DSS compliance
- production WAF/DDoS protection
- external message-broker infrastructure
- a production outbox/event-bus architecture
- bank-grade fraud detection
- multi-user SaaS deployment
- production capacity guarantees

These boundaries are deliberate so that the repository reflects the functionality that is actually implemented and tested.
