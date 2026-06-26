## Exploration: Improve Audit — Admin User Selector + Compliance Graph

### Current State

The audit system has two layers:

**Backend:**
- `GET /api/status/summary` — returns the authenticated user's own current-month audit (`UserSummary`: month, expected_days, reported_days, faltas, falta_dates). Any authenticated user can call it.
- `GET /api/audit/monthly?year=X&month=Y` — admin-only. Returns `UserMonthAudit[]` for ALL `is_audited=True` users. Uses `compute_audit_for_all_users()`.
- `GET /api/audit/users` — admin-only. Lists all users with `id`, `email`, `name`, `is_admin`, `is_audited`, `is_seed`.
- `compute_month_audit()` already supports per-user queries and returns `MonthAudit(user_id, expected_days, reported_days, faltas, falta_dates)`.

**Frontend:**
- `/auditoria` — admin-only page. Shows month picker + cards for each audited user with `reported/expected` counts and expandable falta dates.
- `/` (dashboard) — shows tasks + status editor. Does NOT show any audit summary.
- No chart/graph library installed. Zero frontend dependencies beyond SvelteKit core.
- UI style: neon/cyberpunk dark theme with `GlassPanel`, CSS variables (`--neon-cyan/-pink/-green`), Orbitron + Rajdhani fonts.

**Gap analysis:**
1. The `/auditoria` page shows ALL users at once — no way to drill into a single user's detailed view.
2. Regular users cannot see their own audit data on the dashboard (the `/api/status/summary` endpoint exists but the frontend doesn't call it).
3. No compliance visualization exists anywhere — just raw numbers.

### Affected Areas

- `backend/app/routers/audit.py` — needs a new endpoint for single-user audit (admin can query any user)
- `backend/app/services/audit_service.py` — `compute_month_audit()` already does per-user work; may need a wrapper or reuse directly
- `frontend/src/routes/auditoria/+page.svelte` — needs user selector + compliance graph
- `frontend/src/lib/api/audit.ts` — needs new API function for single-user audit
- `frontend/src/routes/+page.svelte` — (optional) could show the user's own compliance summary
- `frontend/src/lib/components/` — new `ComplianceGauge` component (pure CSS/SVG, no library)

### Approaches

#### 1. Admin User Selector on `/auditoria` + Compliance Graph

Add a user dropdown to the existing `/auditoria` page. When an admin selects a user, fetch that user's audit for the selected month and show a compliance graph.

**Backend changes:**
- New endpoint: `GET /api/audit/monthly/{user_id}?year=X&month=Y` → returns `MonthAudit` for a single user (admin-only).
  - Reuses `compute_month_audit()` directly (already exists).
  - Also returns the user's `email` and `name` for display.
- Alternative: reuse `GET /api/audit/monthly` (already returns all users) and filter client-side. This avoids a new endpoint but fetches all users' data even when viewing one.

**Frontend changes:**
- Add user `<select>` populated from `GET /api/audit/users` (filtered to `is_audited=true`).
- On user selection, call the new per-user endpoint.
- Show a `ComplianceGauge` component: a circular progress ring (SVG) showing `reported_days / expected_days` as a percentage, with color coding (green ≥80%, cyan ≥50%, pink <50%).
- Keep the existing "all users" view as default; user selector is an optional filter.

**Pros:**
- Clean separation: all-users overview → drill-down to individual.
- `compute_month_audit()` is already per-user; minimal backend work.
- SVG gauge is lightweight, no library needed, matches the neon theme.

**Cons:**
- New backend endpoint (small, but needs tests).
- User list fetch is an extra API call (cached after first load).

**Effort:** Medium

#### 2. Client-side Filtering Only (No New Backend Endpoint)

Use the existing `GET /api/audit/monthly` response (already returns all audited users). Add a user selector on the frontend that filters the already-loaded data.

**Pros:**
- Zero backend changes.
- Faster to implement.

**Cons:**
- Fetches ALL users' data even when viewing one (wasteful if many users).
- No additional data beyond what's already in the monthly response (no per-day detail).
- Can't show richer per-user info without a new endpoint.

**Effort:** Low

#### 3. Add Compliance Summary to Dashboard (`/`)

Show the authenticated user's own compliance gauge on the main dashboard, using the existing `GET /api/status/summary` endpoint.

**Pros:**
- Users see their own compliance without navigating to `/auditoria`.
- Uses existing endpoint, no backend changes.

**Cons:**
- Separate from the admin audit improvements (could be done independently).
- Dashboard is already task-focused; adding audit might clutter it.

**Effort:** Low

### Recommendation

**Combine approaches 1 + 3:**

1. **Backend:** Add `GET /api/audit/monthly/{user_id}?year=X&month=Y` (admin-only). Thin wrapper around `compute_month_audit()` that also returns user email/name. Add tests following existing patterns (in-memory SQLite, `dependency_overrides`).

2. **Frontend `/auditoria`:** Add a user selector (`<select>`) above the month picker. Default = "Todos los usuarios" (current behavior). When a specific user is selected, show their detailed audit card with a `ComplianceGauge` SVG component. The gauge shows `reported_days / expected_days` as a percentage ring.

3. **Frontend `/` (dashboard):** Add a small compliance summary card using the existing `GET /api/status/summary`. A compact version of the gauge (no user selector needed — it's always the current user).

4. **ComplianceGauge component:** Pure SVG + CSS. No chart library. A circular progress ring with neon colors. Reusable across both pages.

### SVG Gauge Design

```
       ┌──────────┐
      ╱  85%      ╲
     │   ╭────╮    │
     │  ╱      ╲   │  ← SVG circle with stroke-dasharray
     │ │  ✓     │  │
     │  ╲      ╱   │
     │   ╰────╯    │
      ╲  17/20    ╱
       └──────────┘
```

- Outer ring: background (glass-border color)
- Inner arc: filled proportionally (neon-green ≥80%, neon-cyan ≥50%, neon-pink <50%)
- Center text: percentage number
- Below: "X de Y días" label

### Risks

- **SVG complexity:** Pure SVG gauges can be fiddly on edge cases (0%, 100%, animation). Mitigation: keep it simple, test with boundary values.
- **User list size:** If many users, the `<select>` could be long. Mitigation: sort alphabetically, show email for disambiguation. Could upgrade to a searchable dropdown later.
- **New endpoint tests:** Need to follow the existing test pattern (in-memory SQLite, `dependency_overrides` for `require_admin`). The existing `test_audit_admin_router.py` provides a solid template.
- **Spanish UI strings:** All new labels must be in español neutro (tú form), per project rules.

### Ready for Proposal

**Yes.** The scope is clear:
- 1 new backend endpoint (+ tests)
- 1 new frontend component (`ComplianceGauge`)
- Modifications to `/auditoria` page (user selector + gauge)
- Optional: small compliance card on `/` dashboard

Estimated effort: Medium. The backend work is minimal (wrapper around existing service). The frontend work is the gauge component + page integration.
