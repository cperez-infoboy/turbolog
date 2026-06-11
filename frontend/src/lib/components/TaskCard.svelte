<script lang="ts">
	import type { Task } from '$lib/api/tasks';

	interface Props {
		task: Task;
		selected?: boolean;
		hasReport?: boolean;
		onclick?: (task: Task) => void;
	}

	let { task, selected = false, hasReport = false, onclick }: Props = $props();
</script>

<button
	class="task-card {selected ? 'selected' : ''} {hasReport ? 'has-report' : ''}"
	onclick={() => onclick?.(task)}
>
	<div class="task-header">
		<span class="task-key">{task.jira_key}</span>
		{#if task.priority}
			<span class="priority-dot" title={task.priority}></span>
		{/if}
	</div>
	<p class="task-summary">{task.summary}</p>
	<div class="task-footer">
		<span class="status-badge">{task.status}</span>
		{#if hasReport}
			<span class="report-badge">Reported</span>
		{/if}
	</div>
</button>

<style>
	.task-card {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		background: var(--glass-bg);
		backdrop-filter: blur(10px);
		-webkit-backdrop-filter: blur(10px);
		border: 1px solid var(--glass-border);
		border-radius: var(--border-radius);
		padding: 1.25rem;
		cursor: pointer;
		text-align: left;
		width: 100%;
		transition:
			transform var(--transition-speed) ease,
			border-color var(--transition-speed) ease,
			box-shadow var(--transition-speed) ease;
	}

	.task-card:hover {
		transform: translateY(-5px);
		border-color: var(--glass-border-hover);
		box-shadow: 0 0 15px rgba(0, 255, 255, 0.15);
	}

	.selected {
		border-color: rgba(0, 255, 255, 0.6);
		box-shadow:
			0 0 20px rgba(0, 255, 255, 0.15),
			inset 0 0 20px rgba(0, 255, 255, 0.05);
	}

	.selected:hover {
		border-color: rgba(0, 255, 255, 0.7);
	}

	.task-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.task-key {
		font-family: var(--font-heading);
		font-size: 0.8rem;
		font-weight: 700;
		color: var(--neon-cyan);
		letter-spacing: 0.05em;
	}

	.priority-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--neon-pink);
		box-shadow: 0 0 6px var(--neon-pink);
	}

	.task-summary {
		font-family: var(--font-body);
		font-size: 0.95rem;
		color: var(--text-primary);
		margin: 0;
		line-height: 1.4;
		display: -webkit-box;
		-webkit-line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}

	.task-footer {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		margin-top: 0.25rem;
	}

	.status-badge {
		font-family: var(--font-body);
		font-size: 0.75rem;
		font-weight: 600;
		color: var(--text-secondary);
		background: rgba(0, 204, 204, 0.1);
		padding: 0.2rem 0.6rem;
		border-radius: 4px;
		border: 1px solid rgba(0, 204, 204, 0.2);
	}

	.report-badge {
		font-family: var(--font-body);
		font-size: 0.7rem;
		font-weight: 600;
		color: var(--neon-green);
		background: rgba(0, 255, 136, 0.1);
		padding: 0.15rem 0.5rem;
		border-radius: 4px;
		border: 1px solid rgba(0, 255, 136, 0.2);
	}
</style>
