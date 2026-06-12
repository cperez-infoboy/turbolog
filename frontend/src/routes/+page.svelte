<script lang="ts">
	import { onMount } from 'svelte';
	import { getAuthState } from '$lib/stores/auth.svelte';
	import {
		getTasksState,
		fetchTasks,
		selectTask
	} from '$lib/stores/tasks.svelte';
	import type { StatusReportWithSummary } from '$lib/api/status';
	import { getReportsByDate } from '$lib/api/status';
	import TaskList from '$lib/components/TaskList.svelte';

	const auth = getAuthState();
	const tasks = getTasksState();

	let reportsByTask = $state<Map<string, StatusReportWithSummary>>(new Map());
	let date = $state(todayString());

	function todayString(): string {
		return new Date().toISOString().split('T')[0];
	}

	onMount(async () => {
		await fetchTasks();
		await loadReports();
	});

	async function loadReports() {
		try {
			const reports = await getReportsByDate(date);
			reportsByTask = new Map(reports.map((r) => [r.task_key, r]));
		} catch {
			reportsByTask = new Map();
		}
	}

	function handleSelectTask(task: { jira_key: string }) {
		selectTask(task.jira_key);
	}

	function handleReportSaved() {
		loadReports();
	}
</script>

<svelte:head>
	<title>Turbolog — Panel</title>
</svelte:head>

<div class="dashboard">
	<div class="date-bar">
		<label for="report-date">Fecha</label>
		<input id="report-date" type="date" bind:value={date} onchange={loadReports} />
	</div>

	<TaskList
		tasks={tasks.tasks}
		selectedTaskId={tasks.selectedTaskId}
		{reportsByTask}
		{date}
		loading={tasks.loading}
		onSelectTask={handleSelectTask}
		onReportSaved={handleReportSaved}
	/>
</div>

<style>
	.dashboard {
		display: flex;
		flex-direction: column;
		gap: 1.5rem;
		padding: 6rem 5% 2rem;
		max-width: 800px;
		margin: 0 auto;
		min-height: 100vh;
	}

	.date-bar {
		display: flex;
		align-items: center;
		gap: 1rem;
	}

	.date-bar label {
		font-family: var(--font-heading);
		font-size: 0.85rem;
		font-weight: 700;
		color: var(--text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.1em;
	}

	.date-bar input {
		background: rgba(0, 0, 0, 0.4);
		border: 1px solid var(--glass-border);
		border-radius: 8px;
		padding: 0.6rem 1rem;
		color: var(--text-primary);
		font-family: var(--font-body);
		font-size: 1rem;
		outline: none;
		transition: border-color var(--transition-speed) ease;
	}

	.date-bar input:focus {
		border-color: var(--neon-cyan);
	}

	@media (max-width: 900px) {
		.dashboard {
			padding-top: 5rem;
		}
	}
</style>
