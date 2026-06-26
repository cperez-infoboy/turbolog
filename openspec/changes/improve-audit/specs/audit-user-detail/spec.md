# audit-user-detail Specification

## Purpose

**Layer: Backend.** Admin-only endpoint to query a single audited user's monthly compliance data, wrapping the existing `compute_month_audit()` service with user metadata (email, name).

## Requirements

### Requirement: Per-user audit endpoint

The system SHALL expose `GET /api/audit/monthly/{user_id}?year={Y}&month={M}` returning a single user's `MonthAudit` fields (`expected_days`, `reported_days`, `faltas`, `falta_dates`) plus `email` and `name`.

#### Scenario: Happy path — admin queries a specific user

- GIVEN an authenticated admin user
- WHEN they request `GET /api/audit/monthly/{user_id}?year=2026&month=6`
- THEN the response status is 200
- AND the body contains `expected_days`, `reported_days`, `faltas`, `falta_dates`, `email`, and `name`

#### Scenario: Non-admin is rejected

- GIVEN an authenticated non-admin user
- WHEN they request `GET /api/audit/monthly/{user_id}?year=2026&month=6`
- THEN the response status is 403

#### Scenario: Unauthenticated request is rejected

- GIVEN no valid JWT cookie
- WHEN they request `GET /api/audit/monthly/{user_id}?year=2026&month=6`
- THEN the response status is 401

### Requirement: User not found

The system SHALL return 404 when `user_id` does not exist or the user is not audited (`is_audited=false`).

#### Scenario: Non-existent user ID

- GIVEN an authenticated admin
- WHEN they request `GET /api/audit/monthly/99999?year=2026&month=6`
- THEN the response status is 404

#### Scenario: User exists but is not audited

- GIVEN an authenticated admin and a user with `is_audited=false`
- WHEN they request that user's monthly audit
- THEN the response status is 404

### Requirement: Invalid date parameters

The system SHALL return 422 when `year` or `month` are missing or out of valid range.

#### Scenario: Missing month parameter

- GIVEN an authenticated admin
- WHEN they request `GET /api/audit/monthly/{user_id}?year=2026` (no month)
- THEN the response status is 422

#### Scenario: Month out of range

- GIVEN an authenticated admin
- WHEN they request `GET /api/audit/monthly/{user_id}?year=2026&month=13`
- THEN the response status is 422
