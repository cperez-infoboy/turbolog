import { api } from './client';

export interface StatusReport {
	id: string;
	task_key: string;
	content: string;
	date: string;
	created_at?: string;
	updated_at: string;
}

export interface StatusReportWithSummary {
	id: string;
	task_key: string;
	task_summary: string;
	content: string;
	date: string;
	updated_at: string;
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

export async function getReportsByDate(date: string): Promise<StatusReportWithSummary[]> {
	return api<StatusReportWithSummary[]>(`/api/status?date=${date}`);
}

export async function getTodayReports(): Promise<StatusReportWithSummary[]> {
	return api<StatusReportWithSummary[]>('/api/status/today');
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
