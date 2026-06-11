<script lang="ts">
	import type { Task } from '$lib/api/tasks';
	import type { StatusReport } from '$lib/api/status';
	import { getReportsByDate } from '$lib/api/status';
	import StatusEditor from './StatusEditor.svelte';
	import GlassPanel from './GlassPanel.svelte';

	interface Props {
		selectedTask: Task | null;
		date: string;
		onReportSaved?: () => void;
	}

	let { selectedTask, date, onReportSaved }: Props = $props();

	let reports = $state<Map<string, StatusReport>>(new Map());
	let loading = $state(false);

	// Fetch reports when date changes
	$effect(() => {
		const currentDate = date;
		loadReports(currentDate);
	});

	async function loadReports(targetDate: string) {
		loading = true;
		try {
			const result = await getReportsByDate(targetDate);
			reports = new Map(result.map((r) => [r.task_key, r as unknown as StatusReport]));
		} catch {
			reports = new Map();
		} finally {
			loading = false;
		}
	}

	function getReportForTask(task: Task | null): StatusReport | null {
		if (!task) return null;
		return reports.get(task.jira_key) ?? null;
	}
</script>

<GlassPanel padding="2rem">
	<div class="status-panel">
		<div class="date-display">
			<label for="status-date">Date</label>
			<input
				id="status-date"
				type="date"
				value={date}
				onchange={(e) => {
					const input = e.target as HTMLInputElement;
					// Parent component should handle date changes via prop
				}}
				disabled
			/>
		</div>

		{#if selectedTask}
			<StatusEditor
				task={selectedTask}
				report={getReportForTask(selectedTask)}
				{date}
				onSave={() => {
					loadReports(date);
					onReportSaved?.();
				}}
			/>
		{:else}
			<div class="placeholder">
				<p>Select a task to write a status report</p>
			</div>
		{/if}
	</div>
</GlassPanel>

<style>
	.status-panel {
		display: flex;
		flex-direction: column;
		gap: 1.5rem;
	}

	.date-display {
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
	}

	.date-display label {
		font-family: var(--font-body);
		font-size: 0.85rem;
		color: var(--text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.date-display input {
		background: rgba(0, 0, 0, 0.4);
		border: 1px solid var(--glass-border);
		border-radius: 8px;
		padding: 0.6rem 1rem;
		color: var(--text-primary);
		font-family: var(--font-body);
		font-size: 1rem;
		outline: none;
		width: fit-content;
	}

	.date-display input:focus {
		border-color: var(--neon-cyan);
	}

	.placeholder {
		text-align: center;
		padding: 4rem 1rem;
	}

	.placeholder p {
		font-family: var(--font-body);
		color: var(--text-secondary);
		opacity: 0.5;
		margin: 0;
	}
</style>
