# Design: Improve Audit — Admin User Selector + Compliance Gauge + Dashboard Card

## Technical Approach

Extend the existing audit system with three additions: a backend endpoint for per-user audit queries, a reusable SVG compliance gauge component, and integration into both `/auditoria` (admin drill-down) and `/` (user's own summary). All new code follows existing patterns — the backend wraps `compute_month_audit()`, the frontend uses Svelte 5 runes with `$state`/`$derived`.

## Architecture Decisions

| Decision | Option A | Option B | Choice | Rationale |
|----------|----------|----------|--------|-----------|
| Per-user endpoint | New `GET /audit/monthly/{user_id}` | Client-side filter from `GET /audit/monthly` | **A** | Avoids fetching all users for single-user view; enables future per-day detail; `compute_month_audit()` already handles per-user |
| `is_audited` on `/me` | Add to `/me` response + `UserInfo` | Separate endpoint | **A** | Dashboard needs `is_audited` to gate card visibility; adding one field to existing `/me` is minimal; follows existing `is_admin` pattern |
| Gauge rendering | Pure SVG `stroke-dasharray` | CSS `conic-gradient` | **SVG** | Better browser support for partial arcs; easier color switching via `stroke`; `conic-gradient` needs vendor prefixes for older browsers |
| User selector | Plain `<select>` | Searchable combobox | **`<select>`** | Low user count expected; matches existing month input style; searchable is out of scope per proposal |

## Data Flow

```
Dashboard (/)                           Auditoria (/auditoria)
     │                                        │
     ▼                                        ▼
GET /api/status/summary              GET /api/audit/users (load once)
     │                                        │
     ▼                                        ▼
UserSummary {expected, reported}      <select> → userId
     │                                        │
     ▼                                        ▼
ComplianceGauge                      GET /api/audit/monthly/{user_id}?year&month
  (reported, expected)                        │
                                              ▼
                                     UserMonthAudit {expected, reported, faltas}
                                              │
                                              ▼
                                     ComplianceGauge + existing card
```

**Backend per-user endpoint:**
```
GET /api/audit/monthly/{user_id}
  → require_admin (403 if not)
  → fetch User by id (404 if missing or !is_audited)
  → compute_month_audit(async_session, user_id, year, month)
  → return { user_id, email, name, expected_days, reported_days, faltas, falta_dates }
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/app/routers/audit.py` | Modify | Add `GET /monthly/{user_id}` endpoint (~25 lines) |
| `backend/tests/test_audit_admin_router.py` | Modify | Add `TestUserMonthlyReport` class (happy path, 403, 404, 422) |
| `backend/app/routers/auth.py` | Modify | Add `is_audited` to `/me` response shape |
| `frontend/src/lib/api/auth.ts` | Modify | Add `is_audited: boolean` to `UserInfo` |
| `frontend/src/lib/api/audit.ts` | Modify | Add `getUserMonthlyAudit()` function + `UserDetailAudit` type |
| `frontend/src/lib/components/ComplianceGauge.svelte` | Create | SVG circular gauge component |
| `frontend/src/routes/auditoria/+page.svelte` | Modify | Add user `<select>`, fetch per-user audit, render gauge in cards |
| `frontend/src/routes/+page.svelte` | Modify | Add compliance card section (gated by `is_audited`) |

## Interfaces / Contracts

**Backend response — `GET /api/audit/monthly/{user_id}?year=2026&month=6`:**

```python
# Pydantic model (reuse existing MonthAudit fields + user metadata)
class UserDetailAudit(BaseModel):
    user_id: str
    user_email: str
    user_name: str
    expected_days: int
    reported_days: int
    faltas: int
    falta_dates: list[date]
```

**Frontend TypeScript types:**

```typescript
// In audit.ts
interface UserDetailAudit {
    user_id: string;
    user_email: string;
    user_name: string;
    expected_days: number;
    reported_days: number;
    faltas: number;
    falta_dates: string[];
}
```

**ComplianceGauge props:**

```typescript
interface Props {
    reported: number;
    expected: number;
    size?: number;      // SVG diameter in px, default 120
    strokeWidth?: number; // default 10
}
```

**SVG gauge math:**

```
Circumference C = 2 * π * r
Filled arc = C * (percentage / 100)
stroke-dasharray: "{filled} {C - filled}"
stroke-dashoffset: C / 4  (rotate to 12 o'clock start)
```

Color thresholds via `$derived`:
- `>= 80%` → `var(--neon-green)`
- `>= 50%` → `var(--neon-cyan)`
- `< 50%` → `var(--neon-pink)`

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `ComplianceGauge` renders correct fill at 0%, 50%, 80%, 100%; "Sin datos" when expected=0 | Svelte component test or manual verification |
| Integration | `GET /audit/monthly/{user_id}` happy path, 403 non-admin, 404 missing/non-audited user, 422 bad params | `httpx.AsyncClient` + in-memory SQLite, follow `test_audit_admin_router.py` pattern |
| Integration | `/me` returns `is_audited` field | Extend existing auth tests or verify via API |

**Test cases for new endpoint (in `TestUserMonthlyReport`):**
1. Admin queries audited user → 200 with correct fields
2. Non-admin → 403
3. Non-existent user_id → 404
4. User exists but `is_audited=false` → 404
5. Missing `month` param → 422
6. Month=13 → 422

## Migration / Rollout

No migration required. No new DB tables or columns. The `/me` response gains one field (`is_audited`) — backward-compatible additive change.

## Open Questions

- [ ] Should the dashboard compliance card be collapsible to avoid cluttering the task-focused layout?
