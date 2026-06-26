# Tasks: Improve Audit — Admin User Selector + Compliance Gauge + Dashboard Card

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~315 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: Yes
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Backend: per-user audit endpoint + is_audited on /me | PR 1 | T1–T3; tests included; no frontend changes |
| 2 | Frontend: gauge component + API types + integration | PR 2 | T4–T7; depends on PR 1 backend contract |

> With ~315 total lines, a single PR is acceptable. Split only if reviewer prefers backend-first review.

## Phase 1: Backend — Auth Contract (is_audited on /me)

- [x] **T1** — `backend/app/routers/auth.py`: add `is_audited` to `/me` response dict (1 line). `backend/tests/test_auth.py` or inline verification: `GET /me` returns `is_audited` boolean. `frontend/src/lib/api/auth.ts`: add `is_audited: boolean` to `UserInfo`. `frontend/src/lib/stores/auth.svelte.ts`: add `get isAudited()` getter.
  - *type*: backend + frontend | *tdd*: yes | *estimated_lines*: ~15
  - *spec_refs*: audit-dashboard-card (gates card on `is_audited`)
  - *dependencies*: none
  - *acceptance*: `GET /me` returns `is_audited` field; `getAuthState().isAudited` reflects it

## Phase 2: Backend — Per-User Audit Endpoint (TDD)

- [x] **T2** — RED: `backend/tests/test_audit_admin_router.py` — add `TestUserMonthlyReport` class with 6 test cases: (1) admin queries audited user → 200 with correct fields, (2) non-admin → 403, (3) non-existent user_id → 404, (4) user exists but `is_audited=false` → 404, (5) missing `month` param → 422, (6) month=13 → 422. Follow existing `_build_app`/`_seed_user`/`admin_client` pattern.
  - *type*: backend | *tdd*: RED | *estimated_lines*: ~70
  - *spec_refs*: audit-user-detail (all scenarios)
  - *dependencies*: T1 (needs is_audited on user model)
  - *acceptance*: all 6 tests fail with 404/AttributeError (endpoint doesn't exist yet)

- [x] **T3** — GREEN: `backend/app/routers/audit.py` — add `GET /monthly/{user_id}?year&month` endpoint. Define `UserDetailAudit` Pydantic model (user_id, user_email, user_name, expected_days, reported_days, faltas, falta_dates). Validate month 1–12, year 2000–2100. Fetch User by id, check `is_audited`, call `compute_month_audit(async_session, user_id, year, month)`. Return model with user metadata. `backend/app/services/audit_service.py`: add `UserDetailAudit` model if not reusing inline.
  - *type*: backend | *tdd*: GREEN | *estimated_lines*: ~35
  - *spec_refs*: audit-user-detail (endpoint requirement)
  - *dependencies*: T2
  - *acceptance*: all 6 tests from T2 pass; `uv run pytest -q` green

## Phase 3: Frontend — API Layer + ComplianceGauge Component

- [x] **T4** — `frontend/src/lib/api/audit.ts`: add `UserDetailAudit` interface (user_id, user_email, user_name, expected_days, reported_days, faltas, falta_dates) and `getUserMonthlyAudit(userId, year, month)` function.
  - *type*: frontend | *tdd*: no | *estimated_lines*: ~20
  - *spec_refs*: audit-user-detail (frontend contract)
  - *dependencies*: T3 (backend endpoint must exist)
  - *acceptance*: `npm run check` passes; type matches backend response

- [x] **T5** — `frontend/src/lib/components/ComplianceGauge.svelte`: create SVG circular progress ring. Props: `reported: number`, `expected: number`, `size?: number` (default 120), `strokeWidth?: number` (default 10). SVG math: `C = 2πr`, `filled = C * (percentage / 100)`, `stroke-dasharray: "{filled} {C - filled}"`, `stroke-dashoffset: C / 4`. Color thresholds via `$derived`: ≥80% → `var(--neon-green)`, ≥50% → `var(--neon-cyan)`, <50% → `var(--neon-pink)`. Center text: percentage. Label below: "{X} de {Y} días". Guard: `expected=0` → "Sin datos". All text español neutro.
  - *type*: frontend | *tdd*: no | *estimated_lines*: ~80
  - *spec_refs*: compliance-gauge (all requirements)
  - *dependencies*: none (pure component)
  - *acceptance*: renders at 0%, 50%, 80%, 100%; "Sin datos" when expected=0; `svelte-autofixer` clean

## Phase 4: Frontend — Page Integration

- [x] **T6** — `frontend/src/routes/auditoria/+page.svelte`: add user `<select>` dropdown populated from `getAuditUsers()` (filtered `is_audited=true`, sorted by email). Default option: "Todos los usuarios" (current all-users behavior). On user selection, call `getUserMonthlyAudit(userId, year, month)` and render `ComplianceGauge` in the user's audit card. When "Todos" selected, use existing `getMonthlyAudit()` flow (no gauge). Import `ComplianceGauge` and `getAuditUsers`/`getUserMonthlyAudit`.
  - *type*: frontend | *tdd*: no | *estimated_lines*: ~60
  - *spec_refs*: audit-user-detail (user selector), compliance-gauge (integration)
  - *dependencies*: T4, T5
  - *acceptance*: dropdown shows audited users; selecting a user shows gauge; "Todos" shows current behavior

- [x] **T7** — `frontend/src/routes/+page.svelte`: add compliance summary card gated by `auth.isAudited`. Fetch data from existing `GET /api/status/summary` (returns `expected_days`, `reported_days`). Render compact `ComplianceGauge` with title "Tu cumplimiento". Handle API errors with español neutro message, skip gauge on error. Card uses `GlassPanel` with compact padding.
  - *type*: frontend | *tdd*: no | *estimated_lines*: ~50
  - *spec_refs*: audit-dashboard-card (all requirements)
  - *dependencies*: T1 (needs `isAudited`), T5 (needs ComplianceGauge)
  - *acceptance*: audited user sees card; non-audited sees nothing; error handled gracefully

## Dependency Graph

```
T1 (auth: is_audited)
├── T2 (RED: tests for per-user endpoint) ──→ T3 (GREEN: implement endpoint)
│                                               └── T4 (frontend API types)
T5 (ComplianceGauge component) ──────────────────┤
                                                  ├── T6 (auditoria page integration)
T1 ──────────────────────────────────────────────┤
                                                  └── T7 (dashboard compliance card)
```

**Critical path**: T1 → T2 → T3 → T4 → T6 (audit page fully functional)
**Parallel track**: T5 can start independently of T2/T3 (pure component)
**Final integration**: T6 and T7 can be done in either order after their deps
