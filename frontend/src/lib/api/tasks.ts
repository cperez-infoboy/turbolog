import { api } from './client';

export interface Task {
	jira_key: string;
	summary: string;
	status: string;
	status_category: string | null;
	priority: string | null;
	project_key: string | null;
	project_name: string | null;
	updated: string;
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
