import { api } from './client';

export interface StatusReport {
	id: string;
	task_key: string;
	content: string;
	date: string;
	created_at?: string;
	updated_at: string;
	jira_comment_id?: string | null;
}

export interface StatusReportWithSummary {
	id: string;
	task_key: string;
	task_summary: string;
	content: string;
	date: string;
	updated_at: string;
	jira_comment_id?: string | null;
}

export interface DayReports {
	reports: StatusReportWithSummary[];
	finalized: boolean;
	finalized_at: string | null;
}

export interface FinalizeFailure {
	task_key: string;
	error: string;
}

export interface FinalizeMissing {
	task_key: string;
	task_summary?: string | null;
}

export interface FinalizeResult {
	finalized: boolean;
	posted: number;
	finalized_at?: string;
	failed?: FinalizeFailure[];
	/** Present only on 422: in-progress tasks lacking a status for the day. */
	missing?: FinalizeMissing[];
}

export interface UserSummary {
	month: string;
	expected_days: number;
	reported_days: number;
	faltas: number;
	falta_dates: string[];
}

export async function createReport(
	taskKey: string,
	date: string,
	content: string
): Promise<StatusReport> {
	return api<StatusReport>('/api/status', {
		method: 'POST',
		body: JSON.stringify({ task_key: taskKey, date, content })
	});
}

export async function getReportsByDate(date: string): Promise<DayReports> {
	return api<DayReports>(`/api/status?date=${date}`);
}

export async function getTodayReports(): Promise<DayReports> {
	return api<DayReports>('/api/status/today');
}

export async function getSummary(): Promise<UserSummary> {
	return api<UserSummary>('/api/status/summary');
}

export async function updateReport(id: string, content: string): Promise<StatusReport> {
	return api<StatusReport>(`/api/status/${id}`, {
		method: 'PUT',
		body: JSON.stringify({ content })
	});
}

export async function deleteReport(id: string): Promise<void> {
	await api(`/api/status/${id}`, { method: 'DELETE' });
}

/**
 * Improve a status draft with an OpenAI-compatible LLM (server-side call).
 * Sends the draft plus the cached task context and returns the improved text.
 * The result is applied to the editor for the user to review before saving —
 * nothing is persisted by this call. Throws `ApiError` (with `.status`) on
 * failure; the 401 short-circuit in `api<T>()` keeps the auth store in sync.
 */
export async function improveStatus(taskKey: string, content: string): Promise<string> {
	const data = await api<{ content: string }>('/api/status/improve', {
		method: 'POST',
		body: JSON.stringify({ task_key: taskKey, content })
	});
	return data.content;
}

/**
 * Finalize a day: POST all status reports for `date` to JIRA.
 *
 * The shared `api<T>()` helper throws `ApiError` on any non-2xx, and `ApiError`
 * only exposes `status` + the raw response text — the parsed JSON body is lost.
 * We NEED the 502 body (the list of failed task keys) to render a useful error
 * message in the UI. Two options were considered:
 *   (a) extend ApiError to carry the parsed body — touches a shared helper used
 *       across the app for a single call-site, bigger blast radius.
 *   (b) do the fetch inline here, mirroring `client.ts` (credentials: include,
 *       JSON headers) and handle 502 as a normal return value.
 * We pick (b): the 502 is a documented, expected outcome of THIS endpoint, so
 * treating it as data rather than an error keeps semantics honest. The 401
 * short-circuit is preserved (re-thrown as ApiError) so the auth store still
 * detects a dropped session.
 */
export async function finalizeDay(date: string): Promise<FinalizeResult> {
	const response = await fetch('/api/status/finalize', {
		method: 'POST',
		credentials: 'include',
		headers: {
			'Content-Type': 'application/json'
		},
		body: JSON.stringify({ date })
	});

	if (response.status === 401) {
		// Preserve the auth-store short-circuit behavior.
		const { ApiError } = await import('./client');
		throw new ApiError(401, 'Unauthorized');
	}

	if (response.status === 422) {
		// In-progress task(s) missing a status — expected, return the
		// structured payload so the UI can render exactly which tasks block
		// the close. Same rationale as the 502-as-data path below.
		const body = (await response.json()) as {
			finalized: false;
			missing: FinalizeMissing[];
		};
		return {
			finalized: false,
			posted: 0,
			missing: body.missing
		};
	}

	if (response.status === 502) {
		// Partial JIRA failure — expected, return the structured payload.
		const body = (await response.json()) as {
			finalized: false;
			posted: number;
			failed: FinalizeFailure[];
		};
		return {
			finalized: false,
			posted: body.posted,
			failed: body.failed
		};
	}

	if (!response.ok) {
		const { ApiError } = await import('./client');
		throw new ApiError(response.status, await response.text());
	}

	return (await response.json()) as FinalizeResult;
}
