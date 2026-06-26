# audit-dashboard-card Specification

## Purpose

**Layer: Frontend.** Authenticated user's own compliance summary card on the main dashboard (`/`). Compact gauge using the existing `GET /api/status/summary` endpoint. No user selector — always shows the current user.

## Requirements

### Requirement: Dashboard shows compliance card

The system SHALL display a compliance summary card on the `/` dashboard for authenticated users who are audited (`is_audited=true`).

#### Scenario: Audited user sees compliance card

- GIVEN an authenticated user with `is_audited=true`
- WHEN the dashboard loads
- THEN a compliance card is visible
- AND it contains a compact `ComplianceGauge` component

#### Scenario: Non-audited user sees no card

- GIVEN an authenticated user with `is_audited=false`
- WHEN the dashboard loads
- THEN no compliance card is displayed

### Requirement: Card uses existing summary endpoint

The card SHALL fetch data from `GET /api/status/summary` (already returns `expected_days`, `reported_days`, `faltas` for the current user's month).

#### Scenario: Data loads from summary endpoint

- GIVEN the dashboard loads for an audited user
- WHEN the card fetches data
- THEN it calls `GET /api/status/summary`
- AND populates the gauge with `reported_days` and `expected_days`

#### Scenario: API error is handled gracefully

- GIVEN the summary endpoint returns an error
- WHEN the card fetches data
- THEN an error message is shown in español neutro
- AND the gauge is not rendered

### Requirement: No user selector

The card SHALL NOT include a user selector — it always displays the authenticated user's own data.

#### Scenario: Card shows current user only

- GIVEN any authenticated audited user
- WHEN the card renders
- THEN no dropdown or user selector is present
- AND the data shown belongs to the current session user

### Requirement: Compact layout

The card SHALL use a compact layout suitable for the task-focused dashboard, not overwhelming existing task cards.

#### Scenario: Card fits dashboard grid

- GIVEN the dashboard with existing task cards
- WHEN the compliance card renders
- THEN it occupies a contained area without expanding the page layout significantly

### Requirement: Spanish UI strings

All card text SHALL be in español neutro (tú form).

#### Scenario: Card title and labels

- GIVEN the compliance card renders
- WHEN visible text is displayed
- THEN the title reads "Tu cumplimiento"
- AND gauge labels follow the `ComplianceGauge` spec (e.g., "17 de 20 días")
