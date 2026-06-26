<script lang="ts">
	import type { Task } from '$lib/api/tasks';
	import type { StatusReportWithSummary } from '$lib/api/status';
	import { getTasksState, toggleSortDirection, setTaskFilter } from '$lib/stores/tasks.svelte';
	import type { SortDirection } from '$lib/stores/tasks.svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import TaskCard from './TaskCard.svelte';
	import LoadingSpinner from './LoadingSpinner.svelte';

	type TaskGroup = { key: string; label: string; tasks: Task[] };

	interface Props {
		tasks: Task[];
		selectedTaskId: string | null;
		reportsByTask: Map<string, StatusReportWithSummary>;
		date: string;
		finalized?: boolean;
		loading?: boolean;
		onSelectTask: (task: Task) => void;
		onReportSaved?: () => void;
	}

	let {
		tasks,
		selectedTaskId,
		reportsByTask,
		date,
		finalized = false,
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

	// Global counts over the FULL task list (not the filtered view), so the totals
	// stay accurate regardless of which tab is active. "All" = active tasks only
	// (in-progress + to-do), matching what the "Todas" tab renders.
	const inProgressCount = $derived(
		tasks.filter((t) => t.status_category === 'indeterminate').length
	);
	const todoCount = $derived(tasks.filter((t) => t.status_category === 'new').length);
	const allCount = $derived(inProgressCount + todoCount);

	// Visibility per active tab. Computed before grouping so an empty filter shows
	// the right empty-state. Reads `tasksStore.taskFilter` inside the $derived to
	// stay reactive (never destructure the store — see top of file).
	const visibleTasks = $derived.by<Task[]>(() => {
		const filter = tasksStore.taskFilter;
		if (filter === 'in-progress') {
			return tasks.filter((t) => t.status_category === 'indeterminate');
		}
		if (filter === 'todo') {
			return tasks.filter((t) => t.status_category === 'new');
		}
		return tasks.filter(
			(t) => t.status_category === 'indeterminate' || t.status_category === 'new'
		);
	});

	// Grouping is a pure presentation concern, recomputed per render (never persisted).
	// Section cross-project ordering = insertion order (= JQL fetch order).
	const groups = $derived.by<TaskGroup[]>(() => {
		const dir = tasksStore.sortDirection;
		const visible = visibleTasks;
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

	// Sort toggle describes the ACTION the next click will perform.
	const toggleLabel = $derived(
		tasksStore.sortDirection === 'newest-first' ? 'Antiguo primero' : 'Reciente primero'
	);

	// Collapsible sections — collapse is the default (focus-first UX).
	// Modeled as the set of sections the user EXPANDED (opt-in), which starts
	// empty = all collapsed. SvelteSet makes in-place mutation reactive, so we
	// add/delete keys directly instead of reassigning a new Set each time.
	let expandedGroups = new SvelteSet<string>();

	// Same group-key calc as the grouping $derived above (line 66).
	function groupKeyOf(task: Task): string {
		return (task.project_key ?? '').trim() || 'UNASSIGNED';
	}

	function isExpanded(key: string): boolean {
		return expandedGroups.has(key);
	}

	function toggleGroup(key: string): void {
		if (expandedGroups.has(key)) {
			expandedGroups.delete(key);
		} else {
			expandedGroups.add(key);
		}
	}

	// selectedTaskId is global and unique (one card open at a time). If a section
	// is collapsed and the user clicks one of its cards, the opened card would
	// stay hidden — so expand the section first, then propagate the selection.
	function handleSelectTask(task: Task): void {
		expandedGroups.add(groupKeyOf(task));
		onSelectTask(task);
	}

	const allExpanded = $derived(
		groups.length > 0 && groups.every((g) => expandedGroups.has(g.key))
	);
	const expandAllLabel = $derived(allExpanded ? 'Colapsar todo' : 'Expandir todo');

	function toggleAll(): void {
		// Snapshot allExpanded BEFORE mutating expandedGroups: $derived is lazy and
		// re-evaluates on read. Reading it AFTER clear() would reflect the
		// already-emptied set (false) and re-expand everything — the "Colapsar todo"
		// bug. Capture the intent first, then mutate.
		const expand = !allExpanded;
		expandedGroups.clear();
		if (expand) {
			for (const g of groups) expandedGroups.add(g.key);
		}
	}
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
			<div class="filter-tabs" role="group" aria-label="Filtro de tareas">
				<button
					type="button"
					class="tab"
					class:active={tasksStore.taskFilter === 'in-progress'}
					aria-pressed={tasksStore.taskFilter === 'in-progress'}
					onclick={() => setTaskFilter('in-progress')}
				>
					En curso
					<span class="count">{inProgressCount}</span>
				</button>
				<button
					type="button"
					class="tab"
					class:active={tasksStore.taskFilter === 'todo'}
					aria-pressed={tasksStore.taskFilter === 'todo'}
					onclick={() => setTaskFilter('todo')}
				>
					Por hacer
					<span class="count">{todoCount}</span>
				</button>
				<button
					type="button"
					class="tab"
					class:active={tasksStore.taskFilter === 'all'}
					aria-pressed={tasksStore.taskFilter === 'all'}
					onclick={() => setTaskFilter('all')}
				>
					Todas
					<span class="count">{allCount}</span>
				</button>
			</div>
			<div class="toolbar-actions">
				<button
					type="button"
					class="icon-btn"
					title={expandAllLabel}
					aria-label={expandAllLabel}
					onclick={toggleAll}
				>
					<svg
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
						stroke-linejoin="round"
						aria-hidden="true"
					>
						<polyline points="15 3 21 3 21 9" />
						<polyline points="9 21 3 21 3 15" />
						<line x1="21" y1="3" x2="14" y2="10" />
						<line x1="3" y1="21" x2="10" y2="14" />
					</svg>
				</button>
				<button
					type="button"
					class="icon-btn"
					title={toggleLabel}
					aria-label={toggleLabel}
					onclick={toggleSortDirection}
				>
					<svg
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
						stroke-linejoin="round"
						aria-hidden="true"
					>
						<path d="m21 16-4 4-4-4" />
						<path d="M17 20V4" />
						<path d="m3 8 4-4 4 4" />
						<path d="M7 4v16" />
					</svg>
				</button>
			</div>
		</div>
		{#if groups.length === 0}
			<div class="empty-state">
				{#if tasksStore.taskFilter === 'in-progress'}
					<p>No hay tareas en curso.</p>
					<p class="hint">
						Revisa "Por hacer"{todoCount > 0 ? ` (${todoCount} pendientes)` : ''}.
					</p>
				{:else if tasksStore.taskFilter === 'todo'}
					<p>No tienes tareas por hacer.</p>
				{:else}
					<p>No hay tareas para mostrar.</p>
				{/if}
			</div>
		{:else}
		<div class="sections">
			{#each groups as group (group.key)}
				<section class="group" class:expanded={isExpanded(group.key)}>
					<button
						type="button"
						class="group-header"
						aria-expanded={isExpanded(group.key)}
						aria-controls="group-cards-{group.key}"
						onclick={() => toggleGroup(group.key)}
					>
						<span class="group-label">{group.label}</span>
						<span class="group-count">{group.tasks.length}</span>
						<span class="chevron" class:open={isExpanded(group.key)} aria-hidden="true"></span>
					</button>
					<div
						id="group-cards-{group.key}"
						class="cards-body"
						class:expanded={isExpanded(group.key)}
					>
						<div class="cards">
							{#each group.tasks as task (task.jira_key)}
								<TaskCard
									{task}
									selected={task.jira_key === selectedTaskId}
									report={reportsByTask.get(task.jira_key)}
									{date}
									{finalized}
									onclick={handleSelectTask}
									{onReportSaved}
								/>
							{/each}
						</div>
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
		align-items: center;
		justify-content: space-between;
		gap: 0.75rem;
		flex-wrap: nowrap;
	}

	.toolbar-actions {
		display: inline-flex;
		gap: 0.4rem;
	}

	.icon-btn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 2rem;
		height: 2rem;
		padding: 0;
		color: var(--text-secondary);
		background: var(--glass-bg);
		border: 1px solid var(--glass-border);
		border-radius: var(--border-radius);
		cursor: pointer;
		transition:
			color var(--transition-speed) ease,
			border-color var(--transition-speed) ease,
			background var(--transition-speed) ease,
			box-shadow var(--transition-speed) ease;
	}

	.icon-btn svg {
		width: 1.1rem;
		height: 1.1rem;
	}

	.icon-btn:hover {
		color: var(--neon-cyan);
		background: var(--glass-bg-hover);
		border-color: var(--glass-border-hover);
		box-shadow: 0 0 8px rgba(0, 255, 255, 0.2);
	}

	.icon-btn:focus-visible {
		outline: 2px solid var(--neon-cyan);
		outline-offset: 2px;
	}

	.filter-tabs {
		display: inline-flex;
		gap: 0.2rem;
		background: var(--glass-bg);
		border: 1px solid var(--glass-border);
		border-radius: var(--border-radius);
		padding: 0.2rem;
	}

	.tab {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		font-family: var(--font-body);
		font-size: 0.8rem;
		font-weight: 600;
		letter-spacing: 0.02em;
		color: var(--text-secondary);
		background: transparent;
		border: 1px solid transparent;
		border-radius: calc(var(--border-radius) - 4px);
		padding: 0.3rem 0.6rem;
		cursor: pointer;
		transition:
			color var(--transition-speed) ease,
			background var(--transition-speed) ease,
			border-color var(--transition-speed) ease;
	}

	.tab:hover {
		color: var(--neon-cyan);
	}

	.tab.active {
		color: var(--neon-cyan);
		background: var(--glass-bg-hover);
		border-color: var(--glass-border-hover);
		box-shadow: 0 0 8px rgba(0, 255, 255, 0.2);
	}

	.tab:focus-visible {
		outline: 2px solid var(--neon-cyan);
		outline-offset: 2px;
	}

	.tab .count {
		font-size: 0.75rem;
		font-weight: 700;
		opacity: 0.8;
	}

	.sections {
		display: flex;
		flex-direction: column;
		gap: var(--grid-gap);
	}

	.group {
		display: flex;
		flex-direction: column;
		gap: 0;
		transition: gap var(--transition-speed) ease;
	}

	.group.expanded {
		gap: 0.75rem;
	}

	.group-header {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		width: 100%;
		text-align: left;
		font: inherit;
		color: var(--text-primary);
		background: transparent;
		border: none;
		border-bottom: 1px solid var(--glass-border);
		padding: 0 0.25rem 0.4rem;
		cursor: pointer;
		transition: color var(--transition-speed) ease;
	}

	.group-header:hover {
		color: var(--neon-cyan);
	}

	.group-header:focus-visible {
		outline: 2px solid var(--neon-cyan);
		outline-offset: 2px;
	}

	.group-label {
		font-family: var(--font-heading);
		font-weight: 700;
		font-size: 1.05rem;
		letter-spacing: 0.04em;
	}

	.group-count {
		margin-left: auto;
		font-family: var(--font-body);
		font-size: 0.85rem;
		color: var(--text-secondary);
		opacity: 0.8;
	}

	.chevron {
		width: 0;
		height: 0;
		border-left: 5px solid transparent;
		border-right: 5px solid transparent;
		border-top: 6px solid currentColor;
		opacity: 0.7;
		transition: transform var(--transition-speed) ease;
	}

	.chevron.open {
		transform: rotate(180deg);
	}

	.cards-body {
		display: grid;
		grid-template-rows: 0fr;
		transition: grid-template-rows var(--transition-speed) ease;
	}

	.cards-body.expanded {
		grid-template-rows: 1fr;
	}

	.cards-body > .cards {
		overflow: hidden;
		min-height: 0;
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
