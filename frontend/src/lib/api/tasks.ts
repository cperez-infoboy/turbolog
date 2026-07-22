import { api } from './client';

export interface Task {
	jira_key: string;
	browse_url?: string | null;
	summary: string;
	status: string;
	status_category: string | null;
	priority: string | null;
	project_key: string | null;
	project_name: string | null;
	updated: string;
	created?: string;
	duedate?: string | null;
	description?: string | null;
}

export async function fetchTasks(refresh: boolean = false): Promise<Task[]> {
	const path = refresh ? '/api/jira/tasks?refresh=true' : '/api/jira/tasks';
	const result = await api<Task[] | { tasks: Task[]; stale: boolean }>(path);
	// Handle both direct array and stale-cache-wrapped responses
	if (Array.isArray(result)) {
		return result;
	}
	return result.tasks;
}

export async function closeTask(
	taskKey: string,
	date: string
): Promise<{ task_key: string; pending_close: boolean }> {
	return await api<{ task_key: string; pending_close: boolean }>(
		`/api/jira/tasks/${taskKey}/close`,
		{ method: 'POST', body: JSON.stringify({ date }) }
	);
}

export async function cancelClose(taskKey: string, date: string): Promise<void> {
	await api(`/api/jira/tasks/${taskKey}/close?date=${encodeURIComponent(date)}`, {
		method: 'DELETE'
	});
}
