<script lang="ts">
	import { onMount } from 'svelte';
	import { getAuthState } from '$lib/stores/auth.svelte';
	import {
		getTasksState,
		fetchTasks,
		selectTask
	} from '$lib/stores/tasks.svelte';
	import { getReportsByDate } from '$lib/api/status';
	import TaskList from '$lib/components/TaskList.svelte';
	import StatusPanel from '$lib/components/StatusPanel.svelte';

	const auth = getAuthState();
	const tasks = getTasksState();

	let reportsByTask = $state<Map<string, { id: string }>>(new Map());
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
			reportsByTask = new Map(
				reports.map((r) => [r.task_key, { id: r.id }])
			);
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
	<title>Turbolog — Dashboard</title>
</svelte:head>

<div class="dashboard">
	<section class="tasks-column">
		<h2 class="column-title">Tasks</h2>
		<TaskList
			tasks={tasks.tasks}
			selectedTaskId={tasks.selectedTaskId}
			{reportsByTask}
			loading={tasks.loading}
			onSelectTask={handleSelectTask}
		/>
	</section>

	<section class="status-column">
		<StatusPanel
			selectedTask={tasks.selectedTask}
			{date}
			onReportSaved={handleReportSaved}
		/>
	</section>
</div>

<style>
	.dashboard {
		display: grid;
		grid-template-columns: 2fr 3fr;
		gap: 1.5rem;
		padding: 6rem 5% 2rem;
		max-width: 1400px;
		margin: 0 auto;
		min-height: 100vh;
	}

	.column-title {
		font-family: var(--font-heading);
		font-size: 0.85rem;
		font-weight: 700;
		color: var(--text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.1em;
		margin-bottom: 1rem;
	}

	.tasks-column {
		display: flex;
		flex-direction: column;
	}

	.status-column {
		display: flex;
		flex-direction: column;
	}

	@media (max-width: 900px) {
		.dashboard {
			grid-template-columns: 1fr;
			padding-top: 5rem;
		}
	}
</style>
