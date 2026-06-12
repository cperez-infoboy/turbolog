<script lang="ts">
	import type { Task } from '$lib/api/tasks';
	import type { StatusReportWithSummary } from '$lib/api/status';
	import TaskCard from './TaskCard.svelte';
	import LoadingSpinner from './LoadingSpinner.svelte';

	interface Props {
		tasks: Task[];
		selectedTaskId: string | null;
		reportsByTask: Map<string, StatusReportWithSummary>;
		date: string;
		loading?: boolean;
		onSelectTask: (task: Task) => void;
		onReportSaved?: () => void;
	}

	let {
		tasks,
		selectedTaskId,
		reportsByTask,
		date,
		loading = false,
		onSelectTask,
		onReportSaved
	}: Props = $props();
</script>

<div class="task-list">
	{#if loading}
		<LoadingSpinner />
	{:else if tasks.length === 0}
		<div class="empty-state">
			<p>No tienes tareas asignadas.</p>
			<p class="hint">Si esperas tareas, contacta a tu administrador.</p>
		</div>
	{:else}
		<div class="cards">
			{#each tasks as task (task.jira_key)}
				<TaskCard
					{task}
					selected={task.jira_key === selectedTaskId}
					report={reportsByTask.get(task.jira_key)}
					{date}
					onclick={onSelectTask}
					{onReportSaved}
				/>
			{/each}
		</div>
	{/if}
</div>

<style>
	.task-list {
		display: flex;
		flex-direction: column;
		gap: var(--grid-gap);
	}

	.cards {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}

	.empty-state {
		text-align: center;
		padding: 3rem 1rem;
	}

	.empty-state p {
		font-family: var(--font-body);
		color: var(--text-secondary);
		margin: 0 0 0.5rem;
	}

	.hint {
		font-size: 0.85rem;
		opacity: 0.6;
	}
</style>
