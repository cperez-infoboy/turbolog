# Proposal: Improve Audit — Admin User Selector + Compliance Gauge + Dashboard Card

## Intent

The `/auditoria` page shows all users at once with no drill-down. Admins can't focus on a single user's compliance. Regular users can't see their own audit data anywhere. Raw numbers (`17/20`) lack visual impact. This change adds user-level drill-down, a visual compliance gauge, and an optional dashboard card.

## Scope

### In Scope
- New backend endpoint: `GET /api/audit/monthly/{user_id}?year&month` (admin-only, returns single-user audit + user metadata)
- New `ComplianceGauge` SVG component (circular progress ring, neon theme, reusable)
- User selector dropdown on `/auditoria` page (default: "Todos los usuarios")
- Compliance gauge integrated into per-user audit cards on `/auditoria`
- Optional compliance summary card on `/` dashboard (authenticated user's own data via existing `/api/status/summary`)

### Out of Scope
- Per-day detail breakdown (future enhancement)
- Searchable/combobox user selector (plain `<select>` for now)
- Historical trend charts (month-over-month comparison)
- Audit period date ranges in the gauge (already handled by AuditPeriod model)

## Capabilities

> `openspec/specs/` is empty — all capabilities are new.

### New Capabilities
- `audit-user-detail`: Admin-only per-user audit query — new backend endpoint wrapping `compute_month_audit()` + user metadata
- `compliance-gauge`: Reusable SVG gauge component — circular progress ring with neon color thresholds (green ≥80%, cyan ≥50%, pink <50%)
- `audit-dashboard-card`: Authenticated user's own compliance summary card on main dashboard

### Modified Capabilities
- None (no existing specs to modify)

## Approach

**Backend:** Add `GET /api/audit/monthly/{user_id}?year&month` — thin wrapper around existing `compute_month_audit()` that returns `MonthAudit` + `email`/`name`. Admin-only via `require_admin`. Tests follow existing `test_audit_admin_router.py` pattern (in-memory SQLite, `dependency_overrides`).

**Frontend `/auditoria`:** Add `<select>` populated from `GET /api/audit/users` (filtered `is_audited=true`). Default = all users (current behavior). On user selection, call per-user endpoint and show `ComplianceGauge` in their card.

**Frontend `/` dashboard:** Add compact `ComplianceGauge` card using existing `GET /api/status/summary`. No user selector — always current user.

**ComplianceGauge:** Pure SVG + CSS, no chart library. Circle with `stroke-dasharray` for progress. Color thresholds via CSS variables (`--neon-green`, `--neon-cyan`, `--neon-pink`). Center: percentage. Below: "X de Y días".

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/routers/audit.py` | Modified | New per-user endpoint |
| `backend/tests/test_audit_admin_router.py` | Modified | Tests for new endpoint |
| `frontend/src/routes/auditoria/+page.svelte` | Modified | User selector + gauge integration |
| `frontend/src/routes/+page.svelte` | Modified | Optional compliance card |
| `frontend/src/lib/components/ComplianceGauge.svelte` | New | SVG gauge component |
| `frontend/src/lib/api/audit.ts` | Modified | New API function for per-user audit |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| SVG edge cases (0%, 100%) | Low | Test boundary values explicitly |
| Long user list in `<select>` | Low | Sort alphabetically, show email |
| Dashboard clutter from new card | Low | Make card compact, collapsible |

## Rollback Plan

Remove the user selector from `/auditoria` (revert to all-users view), remove the dashboard card, and delete the new backend endpoint. The existing `GET /api/audit/monthly` and `GET /api/status/summary` endpoints are untouched — no data model changes.

## Dependencies

- None — uses existing `compute_month_audit()`, existing API endpoints, pure SVG (no new libraries)

## Success Criteria

- [ ] Admin can select a single user on `/auditoria` and see their individual audit with compliance gauge
- [ ] Default view ("Todos los usuarios") still works as before
- [ ] `ComplianceGauge` renders correctly at 0%, 50%, 80%, 100% thresholds
- [ ] Authenticated user sees own compliance card on `/` dashboard
- [ ] All new backend endpoints have tests (admin-only access verified)
- [ ] All UI strings in español neutro (tú form)
