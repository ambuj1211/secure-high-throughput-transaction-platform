# Architecture

## 1. Overview

The system is a single-user, local-first transaction-processing simulation intended to demonstrate production-oriented backend engineering.

The design emphasizes:

* scalability
* reliability
* security
* concurrency
* database correctness
* asynchronous processing
* observability
* testability

It is not a real payment processor.

## 2. High-Level Architecture

```text
                         CLIENT
                           |
                           v
                 +-------------------+
                 | Edge / WAF Layer  |
                 | DDoS / Filtering  |
                 +---------+---------+
                           |
                           v
                 +-------------------+
                 | API Gateway       |
                 | TLS / HSTS        |
                 | Rate Limiting     |
                 +---------+---------+
                           |
                           v
                 +-------------------+
                 | FastAPI Backend   |
                 +---------+---------+
                           |
             +-------------+-------------+
             |             |             |
             v             v             v
        PostgreSQL       Redis       Message Queue
             |             |             |
             |             |      +------+------+
             |             |      |             |
             v             v      v             v
       Transaction DB   Cache   Risk Worker  Analytics Worker
                                  |             |
                                  v             v
                                NumPy         Pandas
```

## 3. Transaction Flow

```text
Client
  |
  | POST /transactions
  v
Authentication
  |
  v
Input Validation
  |
  v
Rate / Velocity Checks
  |
  v
Idempotency Check
  |
  v
Database Transaction
  |
  +--> Transaction Record
  |
  +--> Outbox Event
  |
  v
Return transaction state
  |
  v
Outbox / Queue
  |
  +--> Risk Worker
  |      |
  |      +--> Feature extraction
  |      +--> NumPy risk calculation
  |
  +--> Analytics Worker
         |
         +--> Pandas aggregation
```

## 4. Database Design

Core tables:

### users

```text
id
name
email
status
created_at
```

### accounts

```text
id
user_id
balance
currency
version
updated_at
```

### transactions

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
```

Important constraints:

* unique idempotency key
* foreign keys
* non-negative amount
* valid transaction state transitions

### risk_results

```text
transaction_id
risk_score
decision
model_version
created_at
```

### transaction_events

```text
id
transaction_id
event_type
metadata
created_at
```

### security_events

```text
id
event_type
severity
user_id
source
metadata
created_at
```

## 5. Idempotency

Every transaction creation request should support an idempotency key.

```text
Request
   |
   v
idempotency_key lookup
   |
   +-- exists --> return previous result
   |
   +-- absent --> create transaction
```

The database must enforce uniqueness because an application-only check is vulnerable to concurrent requests.

## 6. Double-Spend Protection

A balance update must be atomic.

Example conceptual flow:

```text
BEGIN
  |
  v
Lock/read account state
  |
  v
Check available balance
  |
  +-- insufficient --> ROLLBACK
  |
  +-- sufficient --> update balance
                       |
                       v
                    COMMIT
```

Concurrency tests must verify that simultaneous withdrawals cannot create an invalid negative balance.

## 7. Risk Engine

The risk engine calculates features such as:

```text
transaction velocity
amount deviation
recent transaction count
new device indicator
new merchant indicator
location anomaly indicator
```

NumPy performs numerical calculations.

The first implementation should be a transparent rule/statistical scoring engine rather than an unexplained ML model.

Example conceptual output:

```text
risk_score = 0.0 ... 1.0

low score     -> normal processing
medium score  -> additional verification / review
high score    -> block or hold according to configured rules
```

## 8. Analytics Engine

Pandas processes synthetic historical transactions for:

* daily transaction counts
* transaction volume
* merchant summaries
* average transaction amount
* anomaly summaries
* failure rates

Large synthetic datasets should be used to benchmark processing performance.

## 9. Redis

Redis can support:

* rate-limit counters
* velocity windows
* short-lived cache
* temporary authentication/risk state

Redis must not become the sole source of truth for financial balances.

## 10. Queue / Asynchronous Processing

A message queue separates transaction acceptance from background processing.

Workers:

```text
Risk Worker
Analytics Worker
Outbox Worker
```

The system should tolerate:

* duplicate messages
* worker restart
* temporary queue failure
* processing retry

## 11. Outbox Pattern

Transaction state and the corresponding event should be committed atomically.

```text
PostgreSQL
+-------------------+
| transaction       |
| outbox_event      |
+-------------------+
          |
          v
     Outbox Worker
          |
          v
       Queue
```

This prevents the failure mode where the transaction commits but event publication is lost.

## 12. Security Architecture

### Edge

* TLS
* HSTS
* WAF/rate limiting in real deployments
* application-layer request limits

### API

* authentication
* authorization
* RBAC
* input validation
* rate limiting
* secure error responses

### Database

* parameterized queries / SQLAlchemy
* least-privilege database credentials
* constraints
* encrypted transport in production

### Application

* no raw card storage
* synthetic payment tokens
* secret management through environment/secret-management mechanisms
* structured security logging
* audit trail

## 13. Observability

```text
FastAPI / Workers
      |
      +--> Metrics --> Prometheus --> Grafana
      |
      +--> Structured Logs
      |
      +--> Security Events
      |
      +--> Audit Events
```

Important metrics:

```text
http_requests_total
http_request_duration
transaction_success_total
transaction_failure_total
risk_decisions_total
queue_depth
db_connection_usage
rate_limit_events_total
security_events_total
```

## 14. Failure Model

Expected failures:

```text
Database unavailable
Redis unavailable
Queue unavailable
Worker crash
Risk timeout
Network timeout
Connection pool exhaustion
Partial transaction failure
Duplicate event
```

Each failure should have:

```text
Detection
Mitigation
Recovery
Automated test
```

## 15. Deployment

Initial target:

```text
Docker Compose
```

Containers:

```text
api
worker
postgres
redis
queue
prometheus
grafana
```

Cloud deployment is optional and should not be required for the resume version.

## 16. Design Principles

1. Database is the source of truth for financial state.
2. Every protected resource requires authorization.
3. Idempotency is enforced at the database boundary.
4. Financial updates are atomic.
5. Background processing is retryable.
6. Security events are observable.
7. Every important failure mode has a test.
8. Performance claims must be backed by measurements.
9. Secrets and payment credentials are never committed.
10. Complexity should be added only when it demonstrates a real engineering requirement.
