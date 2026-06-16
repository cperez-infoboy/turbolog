<script lang="ts">
	import type { Task } from '$lib/api/tasks';
	import type { StatusReportWithSummary } from '$lib/api/status';
	import { getTasksState, toggleSortDirection, toggleTaskFilter } from '$lib/stores/tasks.svelte';
	import type { SortDirection } from '$lib/stores/tasks.svelte';
	import TaskCard from './TaskCard.svelte';
	import LoadingSpinner from './LoadingSpinner.svelte';

	type TaskGroup = { key: string; label: string; tasks: Task[] };

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

	// Keep the store reference (do NOT destructure) — reading `tasksStore.sortDirection`
	// inside a $derived invokes the getter, which reads the underlying $state and stays
	// reactive. Destructuring would snapshot the value once and break the toggle.
	const tasksStore = getTasksState();

	// Comparator for tasks within a section.
	// Primary key: tasks "in progress" (status_category === 'indeterminate') ALWAYS
	// sort first, regardless of the date toggle — "en curso" tasks lead each section.
	// Secondary key: creation date, direction-aware (the toggle flips ONLY this),
	// null-sorts-last so un-backfilled tasks never jump to the top (REQ-SYNC-05).
	function compareTasks(a: Task, b: Task, dir: SortDirection): number {
		const aInProgress = a.status_category === 'indeterminate';
		const bInProgress = b.status_category === 'indeterminate';
		if (aInProgress !== bInProgress) {
			return aInProgress ? -1 : 1;
		}
		const aNull = !a.created;
		const bNull = !b.created;
		if (aNull && bNull) return 0;
		if (aNull) return 1;
		if (bNull) return -1;
		const diff = new Date(b.created!).getTime() - new Date(a.created!).getTime();
		return dir === 'newest-first' ? diff : -diff;
	}

	// Grouping is a pure presentation concern, recomputed per render (never persisted).
	// Section cross-project ordering = insertion order (= JQL fetch order).
	const groups = $derived.by<TaskGroup[]>(() => {
		const dir = tasksStore.sortDirection;
		// Filter BEFORE grouping: default "in progress" only, optionally add To Do.
		const visible = tasksStore.taskFilter === 'in-progress'
			? tasks.filter((t) => t.status_category === 'indeterminate')
			: tasks;
		const map = new Map<string, Task[]>();
		for (const t of visible) {
			const key = (t.project_key ?? '').trim() || 'UNASSIGNED';
			if (!map.has(key)) map.set(key, []);
			map.get(key)!.push(t);
		}
		const out: TaskGroup[] = [];
		for (const [key, items] of map) {
			items.sort((a, b) => compareTasks(a, b, dir));
			const label = key === 'UNASSIGNED' ? 'UNASSIGNED' : (items[0]?.project_name ?? key);
			out.push({ key, label, tasks: items });
		}
		return out;
	});

	// Toggle buttons describe the ACTION the next click will perform.
	const toggleLabel = $derived(
		tasksStore.sortDirection === 'newest-first' ? 'Antiguo primero' : 'Reciente primero'
	);
	const filterLabel = $derived(
		tasksStore.taskFilter === 'in-progress' ? 'Mostrar pendientes' : 'Solo en curso'
	);
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
		<div class="toolbar">
			<button type="button" class="toggle" onclick={toggleTaskFilter}>
				{filterLabel}
			</button>
			<button type="button" class="toggle" onclick={toggleSortDirection}>
				{toggleLabel}
			</button>
		</div>
		{#if groups.length === 0}
			<div class="empty-state">
				<p>No hay tareas en curso.</p>
				<p class="hint">Usá "Mostrar pendientes" para ver las tareas To Do.</p>
			</div>
		{:else}
		<div class="sections">
			{#each groups as group (group.key)}
				<section class="group">
					<header class="group-header">
						<span class="group-label">{group.label}</span>
						<span class="group-count">{group.tasks.length}</span>
					</header>
					<div class="cards">
						{#each group.tasks as task (task.jira_key)}
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
				</section>
			{/each}
		</div>
		{/if}
	{/if}
</div>

<style>
	.task-list {
		display: flex;
		flex-direction: column;
		gap: var(--grid-gap);
	}

	.toolbar {
		display: flex;
		justify-content: flex-end;
		gap: 0.5rem;
		flex-wrap: wrap;
	}

	.toggle {
		font-family: var(--font-body);
		font-size: 0.9rem;
		font-weight: 600;
		letter-spacing: 0.05em;
		text-transform: uppercase;
		color: var(--neon-cyan);
		background: var(--glass-bg);
		border: 1px solid var(--glass-border);
		border-radius: var(--border-radius);
		padding: 0.5rem 1rem;
		cursor: pointer;
		transition: border-color var(--transition-speed) ease, background var(--transition-speed) ease;
	}

	.toggle:hover {
		background: var(--glass-bg-hover);
		border-color: var(--glass-border-hover);
	}

	.toggle:focus-visible {
		outline: 2px solid var(--neon-cyan);
		outline-offset: 2px;
	}

	.sections {
		display: flex;
		flex-direction: column;
		gap: var(--grid-gap);
	}

	.group {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}

	.group-header {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 0.75rem;
		padding: 0 0.25rem;
		border-bottom: 1px solid var(--glass-border);
		padding-bottom: 0.4rem;
	}

	.group-label {
		font-family: var(--font-heading);
		font-weight: 700;
		font-size: 1.05rem;
		color: var(--text-primary);
		letter-spacing: 0.04em;
	}

	.group-count {
		font-family: var(--font-body);
		font-size: 0.85rem;
		color: var(--text-secondary);
		opacity: 0.8;
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
