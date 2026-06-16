import { fetchTasks as apiFetchTasks } from '$lib/api/tasks';
import type { Task } from '$lib/api/tasks';

export type SortDirection = 'newest-first' | 'oldest-first';

let tasks = $state<Task[]>([]);
let selectedTaskId = $state<string | null>(null);
let loading = $state(false);
let error = $state<string | null>(null);
let sortDirection = $state<SortDirection>('newest-first');

export function getTasksState() {
	return {
		get tasks() {
			return tasks;
		},
		get selectedTaskId() {
			return selectedTaskId;
		},
		get loading() {
			return loading;
		},
		get error() {
			return error;
		},
		get selectedTask() {
			return tasks.find((t) => t.jira_key === selectedTaskId) ?? null;
		},
		get sortDirection() {
			return sortDirection;
		}
	};
}

export function toggleSortDirection(): void {
	sortDirection = sortDirection === 'newest-first' ? 'oldest-first' : 'newest-first';
}

export async function fetchTasks(refresh: boolean = false): Promise<void> {
	loading = true;
	error = null;
	try {
		tasks = await apiFetchTasks(refresh);
	} catch (e: unknown) {
		if (e instanceof Error) {
			error = e.message;
		} else {
			error = 'Error al obtener las tareas';
		}
	} finally {
		loading = false;
	}
}

export function selectTask(jiraKey: string | null): void {
	selectedTaskId = jiraKey;
}
