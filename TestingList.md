# Testing List

This document is the master testing checklist for the project.

Legend:

* [ ] Not started
* [~] In progress
* [x] Completed
* [!] Needs investigation

## 1. Unit Tests

### Transaction logic

* [ ] Valid transaction accepted
* [ ] Zero amount rejected
* [ ] Negative amount rejected
* [ ] Invalid currency rejected
* [ ] Invalid user rejected
* [ ] Invalid merchant rejected
* [ ] Transaction state transition validation
* [ ] Idempotency logic
* [ ] Retry logic

### Risk engine

* [ ] Feature calculation
* [ ] Velocity calculation
* [ ] Amount anomaly calculation
* [ ] Risk score calculation
* [ ] Risk threshold behavior
* [ ] Numerical edge cases
* [ ] Empty input handling
* [ ] Large numeric values

### Velocity engine

* [ ] IP velocity
* [ ] User velocity
* [ ] Payment-token velocity
* [ ] BIN velocity using synthetic BIN-like data
* [ ] Device velocity
* [ ] Time-window expiration

## 2. API / Functional Tests

* [ ] POST transaction
* [ ] GET transaction
* [ ] GET user transactions
* [ ] GET merchant transactions
* [ ] Retry endpoint
* [ ] Analytics endpoint
* [ ] Health endpoint
* [ ] Metrics endpoint
* [ ] Authentication required
* [ ] Correct HTTP status codes
* [ ] Error response schema
* [ ] Input validation

## 3. Integration Tests

* [ ] API + PostgreSQL
* [ ] API + Redis
* [ ] API + queue
* [ ] Transaction + risk worker
* [ ] Transaction + analytics worker
* [ ] Outbox + queue
* [ ] Worker retry
* [ ] Transaction rollback
* [ ] Database migration

## 4. Database Tests

* [ ] Foreign-key constraints
* [ ] Unique idempotency key
* [ ] Amount constraints
* [ ] Transaction state constraints
* [ ] Atomic balance update
* [ ] Rollback behavior
* [ ] Concurrent updates
* [ ] Connection pooling
* [ ] Index usage
* [ ] EXPLAIN ANALYZE for critical queries
* [ ] Large transaction table query
* [ ] Pagination correctness

## 5. Security Tests

### SQL Injection

* [ ] Injection in transaction ID
* [ ] Injection in search/filter parameters
* [ ] Injection-like payloads treated as data
* [ ] No dynamic SQL from untrusted input

### BOLA / IDOR

* [ ] User can access own transaction
* [ ] User cannot access another user's transaction
* [ ] User cannot modify another user's transaction
* [ ] User cannot cancel another user's transaction
* [ ] Admin authorization tested separately

### Authentication

* [ ] Invalid credentials rejected
* [ ] Expired token rejected
* [ ] Invalid token rejected
* [ ] Missing token rejected
* [ ] Brute-force throttling
* [ ] Credential-stuffing-style repeated attempts throttled

### Authorization

* [ ] User role restrictions
* [ ] Admin-only endpoint
* [ ] Privilege escalation attempts rejected
* [ ] Resource-level authorization

### Rate limiting / abuse

* [ ] IP rate limit
* [ ] User rate limit
* [ ] Payment-token velocity
* [ ] BIN velocity using synthetic data
* [ ] Device velocity
* [ ] Rate-limit response
* [ ] Window expiration

### Replay / duplication

* [ ] Duplicate idempotency key
* [ ] Same request repeated
* [ ] Replay after completion
* [ ] Concurrent duplicate requests

### XSS

* [ ] Script-like input rejected/encoded
* [ ] Output encoding
* [ ] Content Security Policy headers

### CSRF

* [ ] CSRF protection for cookie-authenticated state-changing requests
* [ ] Missing CSRF token rejected
* [ ] Invalid CSRF token rejected

### Security headers

* [ ] HSTS
* [ ] CSP
* [ ] X-Content-Type-Options
* [ ] Frame protection
* [ ] Secure cookie attributes where applicable

### Sensitive data

* [ ] Payment tokens are synthetic
* [ ] No secrets in logs
* [ ] No credentials in API responses
* [ ] Sensitive fields redacted
* [ ] Error messages do not leak internals

### Dependency / container security

* [ ] pip-audit
* [ ] Bandit
* [ ] Secret scanning
* [ ] Docker image scan
* [ ] Pinned/locked dependencies

## 6. Concurrency Tests

* [ ] 2 simultaneous withdrawals
* [ ] 10 simultaneous withdrawals
* [ ] 100 simultaneous transactions
* [ ] Same transaction concurrently submitted
* [ ] Same idempotency key concurrently submitted
* [ ] Concurrent balance updates
* [ ] Race-condition detection
* [ ] Double-spend prevention
* [ ] No negative balance
* [ ] Correct final balance

## 7. Reliability / Failure Tests

* [ ] PostgreSQL unavailable
* [ ] PostgreSQL timeout
* [ ] Redis unavailable
* [ ] Redis timeout
* [ ] Queue unavailable
* [ ] Worker crash
* [ ] Risk worker timeout
* [ ] Retry succeeds after temporary failure
* [ ] Retry does not duplicate transaction
* [ ] Circuit-breaker behavior if implemented
* [ ] Partial transaction failure
* [ ] Outbox recovery
* [ ] Duplicate event processing
* [ ] Rollback after failure

## 8. Data / Analytics Tests

* [ ] Empty dataset
* [ ] Single transaction
* [ ] Duplicate rows
* [ ] Missing values
* [ ] Invalid values
* [ ] Large dataset
* [ ] Group-by correctness
* [ ] Daily aggregation
* [ ] Merchant aggregation
* [ ] Risk-feature correctness
* [ ] Numerical precision checks

## 9. Performance Tests

### Baseline

* [ ] Establish baseline throughput
* [ ] Establish baseline latency

### Load

* [ ] Normal expected load
* [ ] Increasing concurrent users
* [ ] API throughput
* [ ] Database throughput

### Stress

* [ ] Increase load until degradation
* [ ] Identify bottleneck
* [ ] Record failure threshold

### Spike

* [ ] Sudden traffic increase
* [ ] Recovery after spike

### Soak

* [ ] Long-running test
* [ ] Memory stability
* [ ] Connection stability
* [ ] Queue stability

### Measurements

* [ ] RPS
* [ ] P50
* [ ] P95
* [ ] P99
* [ ] Error rate
* [ ] CPU
* [ ] Memory
* [ ] DB connections
* [ ] Queue depth

## 10. Regression Tests

* [ ] Every fixed bug gets a regression test
* [ ] Security bug regression tests
* [ ] Concurrency bug regression tests
* [ ] Database bug regression tests
* [ ] Performance regression baseline

## 11. CI/CD Tests

* [ ] Tests run on push
* [ ] Tests run on pull request
* [ ] Linting
* [ ] Type checking
* [ ] Unit tests
* [ ] Integration tests
* [ ] Security scans
* [ ] Docker build
* [ ] Container scan
* [ ] Test report
* [ ] Build failure blocks merge

## 12. Final Acceptance Criteria

* [ ] All mandatory tests pass
* [ ] No known critical security issue
* [ ] No duplicate transaction under concurrency test
* [ ] No double spending under concurrency test
* [ ] Failure scenarios behave as designed
* [ ] Load-test results recorded from actual execution
* [ ] README updated with real results
* [ ] Architecture documentation updated
* [ ] CI pipeline passes
