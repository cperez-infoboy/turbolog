<script lang="ts">
	import { onMount } from 'svelte';
	import { getAuthState } from '$lib/stores/auth.svelte';
	import {
		getTasksState,
		fetchTasks,
		selectTask
	} from '$lib/stores/tasks.svelte';
	import type { StatusReportWithSummary } from '$lib/api/status';
	import { getReportsByDate, finalizeDay, getSummary } from '$lib/api/status';
	import { getTelegramStatus } from '$lib/api/telegram';
	import { ApiError } from '$lib/api/client';
	import TaskList from '$lib/components/TaskList.svelte';
	import Button from '$lib/components/Button.svelte';
	import ComplianceGauge from '$lib/components/ComplianceGauge.svelte';

	const auth = getAuthState();
	const tasks = getTasksState();

	let reportsByTask = $state<Map<string, StatusReportWithSummary>>(new Map());
	let date = $state(todayString());
	let finalized = $state(false);
	let finalizedAt = $state<string | null>(null);
	let finalizing = $state(false);
	let finalizeError = $state<string | null>(null);
	let finalizeSuccess = $state(false);
	// Backend-reported missing tasks from a 422 — covers the race where the
	// local `missingStatusTasks` computation was stale (e.g. reports reloaded
	// from another tab) and the server rejected the finalize.
	let finalizeMissing = $state<Array<{ task_key: string; task_summary?: string | null }>>([]);
	let loadError = $state<string | null>(null);

	// Telegram — solo necesitamos saber si está vinculado para el banner.
	// null = aún no se consultó, boolean = estado conocido.
	let telegramLinked = $state<boolean | null>(null);

	// Compliance summary for audited users.
	let complianceReported = $state(0);
	let complianceExpected = $state(0);
	let complianceLoaded = $state(false);
	let complianceError = $state(false);
	let sidebarOpen = $state(true);

	function todayString(): string {
		return new Date().toISOString().split('T')[0];
	}

	onMount(async () => {
		await fetchTasks();
		await loadReports();
		await loadTelegramStatus();
		if (auth.isAudited) {
			await loadCompliance();
		}
	});

	async function loadReports() {
		try {
			const day = await getReportsByDate(date);
			reportsByTask = new Map(day.reports.map((r) => [r.task_key, r]));
			finalized = day.finalized;
			finalizedAt = day.finalized_at;
			finalizeError = null;
			finalizeSuccess = false;
			loadError = null;
		} catch {
			// Transient error — do NOT flip finalized/finalizedAt: the day may
			// still be closed server-side, and reverting to editable would let
			// the user write into a locked day. Preserve last-known lock state
			// and surface the failure as a non-blocking notice.
			loadError = 'No se pudieron cargar los statuses.';
		}
	}

	async function loadTelegramStatus() {
		try {
			const status = await getTelegramStatus();
			telegramLinked = status.linked;
		} catch {
			// Non-critical — Telegram may not be configured.
		}
	}

	async function loadCompliance() {
		try {
			const summary = await getSummary();
			complianceReported = summary.reported_days;
			complianceExpected = summary.expected_days;
			complianceLoaded = true;
			complianceError = false;
		} catch {
			complianceError = true;
		}
	}

	function handleSelectTask(task: { jira_key: string }) {
		selectTask(task.jira_key);
	}

	function handleReportSaved() {
		loadReports();
	}

	// In-progress tasks (status_category 'indeterminate') must each have a
	// non-empty status for the day before it can be closed. Reading the
	// `tasks.tasks` getter directly inside the $derived keeps reactivity honest
	// (destructuring the store getter would snap the reactive link).
	const inProgressTasks = $derived(
		tasks.tasks.filter((t) => t.status_category === 'indeterminate')
	);
	const missingStatusTasks = $derived(
		inProgressTasks.filter((t) => {
			const r = reportsByTask.get(t.jira_key);
			return !r || !r.content.trim().length;
		})
	);

	const finalizeButtonLabel = $derived(finalized ? 'Día cerrado' : 'Cerrar día');

	async function handleFinalize() {
		if (finalized || finalizing) return;
		if (
			!confirm('¿Cerrar el día? Se publicarán los statuses en JIRA y ya no podrás modificarlos.')
		)
			return;

		finalizing = true;
		finalizeError = null;
		finalizeSuccess = false;
		finalizeMissing = [];

		try {
			const result = await finalizeDay(date);
			if (result.finalized) {
				// Flip to closed IMMEDIATELY — the server has confirmed the day
				// is finalized. If the follow-up loadReports() GET fails, the UI
				// must still show the day as closed instead of flashing back to
				// editable.
				finalized = true;
				finalizedAt = result.finalized_at ?? null;
				finalizeSuccess = true;
				try {
					await loadReports();
				} catch {
					// loadReports already set loadError; keep finalizeSuccess
					// and the finalized lock intact.
				}
			} else if (result.missing && result.missing.length > 0) {
				// 422 — backend says these in-progress tasks lack a status.
				// Trust the server's view (it may be fresher than ours) and
				// surface the exact list. Do NOT set finalizeSuccess.
				finalizeMissing = result.missing;
				finalizeError = 'Falta el status de tareas en curso para poder cerrar el día.';
			} else {
				// 502 partial failure — keep the day editable.
				const failedKeys = (result.failed ?? []).map((f) => f.task_key).join(', ');
				finalizeError = `No se pudo cerrar: fallaron ${failedKeys}. Reintenta cuando JIRA esté disponible.`;
			}
		} catch (err) {
			if (err instanceof ApiError) {
				if (err.status === 409) {
					// Already closed (e.g. in another tab) — sync state.
					finalizeError = 'El día ya estaba cerrado.';
					try {
						await loadReports();
					} catch {
						// network failure on sync — keep the 409 notice.
					}
				} else if (err.status === 500) {
					finalizeError =
						'JIRA no está configurado en el servidor. Contactá al administrador.';
				} else {
					finalizeError =
						'No se pudo cerrar el día. Verifica tu conexión e inténtalo nuevamente.';
				}
			} else {
				finalizeError =
					'No se pudo cerrar el día. Verifica tu conexión e inténtalo nuevamente.';
			}
		} finally {
			finalizing = false;
		}
	}
</script>

<svelte:head>
	<title>Turbolog — Panel</title>
</svelte:head>

<div class="dashboard-layout" style="	padding-right: {auth.isAudited && complianceLoaded ? (sidebarOpen ? '230px' : '24px') : '5%'}">
	<div class="dashboard-main">
		<div class="date-bar">
			<label for="report-date">Fecha</label>
			<input id="report-date" type="date" bind:value={date} onchange={loadReports} />
			<Button
				variant="cta"
				onclick={handleFinalize}
				disabled={finalized || missingStatusTasks.length > 0 || finalizing || tasks.loading}
				loading={finalizing}
			>
				{finalizeButtonLabel}
			</Button>
		</div>

		{#if missingStatusTasks.length > 0}
			<p class="finalize-msg warning">
				Falta el status de: {missingStatusTasks
					.map((t) => `${t.jira_key} — ${t.summary}`)
					.join('; ')}.
			</p>
		{/if}
		{#if finalizeMissing.length > 0}
			<p class="finalize-msg warning">
				El servidor rechazó el cierre. Falta el status de: {finalizeMissing
					.map((m) => `${m.task_key}${m.task_summary ? ` — ${m.task_summary}` : ''}`)
					.join('; ')}.
			</p>
		{/if}

		{#if finalizeSuccess}
			<p class="finalize-msg success">Día cerrado. Los statuses se publicaron en JIRA.</p>
		{/if}
		{#if finalizeError}
			<p class="finalize-msg error">{finalizeError}</p>
		{/if}
		{#if loadError}
			<p class="finalize-msg error">{loadError}</p>
		{/if}

		{#if telegramLinked === false}
			<a href="/ajustes" class="telegram-banner">
				📋 No tienes Telegram configurado. Los recordatorios se envían por este canal.
				<span class="telegram-banner-link">Configurar notificaciones →</span>
			</a>
		{/if}

		<TaskList
			tasks={tasks.tasks}
			selectedTaskId={tasks.selectedTaskId}
			{reportsByTask}
			{date}
			{finalized}
			loading={tasks.loading}
			onSelectTask={handleSelectTask}
			onReportSaved={handleReportSaved}
		/>
	</div>

	{#if auth.isAudited && complianceLoaded}
		<aside class="sidebar" class:collapsed={!sidebarOpen}>
			<button
				class="sidebar-toggle"
				onclick={() => (sidebarOpen = !sidebarOpen)}
				aria-label={sidebarOpen ? 'Colapsar panel' : 'Expandir panel'}
				title={sidebarOpen ? 'Colapsar' : 'Expandir'}
			>
				<span class="sidebar-toggle-icon">{sidebarOpen ? '▶' : '◀'}</span>
			</button>
			{#if sidebarOpen}
				<div class="sidebar-content">
					<span class="sidebar-title">Tu cumplimiento</span>
					<ComplianceGauge
						reported={complianceReported}
						expected={complianceExpected}
						size={120}
						strokeWidth={10}
					/>
				</div>
			{/if}
		</aside>
	{/if}
</div>

<style>
	.dashboard-layout {
		display: flex;
		gap: 1.5rem;
		padding: 6rem 5% 2rem;
		max-width: 1100px;
		margin: 0 auto;
		min-height: 100vh;
	}

	.dashboard-main {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 1.5rem;
		min-width: 0;
	}

	.date-bar {
		display: flex;
		align-items: center;
		gap: 1rem;
		flex-wrap: wrap;
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

	.date-bar :global(.btn) {
		margin-left: auto;
		flex-shrink: 0;
	}

	.finalize-msg {
		font-family: var(--font-body);
		font-size: 0.9rem;
		font-weight: 600;
		padding: 0.6rem 1rem;
		border-radius: 8px;
		border: 1px solid var(--glass-border);
		margin: 0;
	}

	.finalize-msg.success {
		color: var(--neon-green);
		background: rgba(0, 255, 136, 0.08);
		border-color: rgba(0, 255, 136, 0.3);
	}

	.finalize-msg.error {
		color: var(--neon-pink);
		background: rgba(255, 0, 255, 0.08);
		border-color: rgba(255, 0, 0, 0.3);
	}

	.finalize-msg.warning {
		color: var(--neon-cyan);
		background: var(--glass-bg);
		border-color: var(--glass-border-hover);
	}

	.telegram-banner {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
		padding: 0.7rem 1.2rem;
		background: var(--glass-bg);
		border: 1px solid var(--glass-border);
		border-radius: 8px;
		font-family: var(--font-body);
		font-size: 0.85rem;
		color: var(--text-secondary);
		text-decoration: none;
		transition:
			border-color var(--transition-speed) ease,
			background var(--transition-speed) ease;
		flex-wrap: wrap;
	}

	.telegram-banner:hover {
		border-color: var(--glass-border-hover);
		background: var(--glass-bg-hover);
	}

	.telegram-banner-link {
		font-weight: 700;
		color: var(--neon-cyan);
		white-space: nowrap;
	}

	/* Sidebar — full-height drawer */
	.sidebar {
		position: fixed;
		top: 0;
		right: 0;
		height: 100vh;
		width: 220px;
		background: rgba(10, 10, 20, 0.95);
		border-left: 1px solid var(--glass-border);
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 1.5rem;
		padding: 5rem 1rem 2rem;
		z-index: 50;
		transition: width 0.25s ease;
		overflow: hidden;
	}

	.sidebar.collapsed {
		width: 16px;
		padding: 5rem 0 2rem;
	}

	.sidebar-toggle {
		position: absolute;
		left: 0;
		top: 0;
		width: 16px;
		height: 100%;
		background: rgba(255, 255, 255, 0.03);
		border: none;
		border-right: 1px solid var(--glass-border);
		cursor: pointer;
		color: var(--text-secondary);
		display: flex;
		align-items: center;
		justify-content: center;
		transition:
			color var(--transition-speed) ease,
			background var(--transition-speed) ease;
		z-index: 2;
	}

	.sidebar-toggle:hover {
		color: var(--neon-cyan);
		background: rgba(0, 255, 255, 0.05);
	}

	.sidebar-toggle-icon {
		font-size: 0.6rem;
		pointer-events: none;
	}

	.sidebar-content {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 1rem;
		padding-top: 0.5rem;
	}

	.sidebar-title {
		font-family: var(--font-heading);
		font-size: 0.75rem;
		font-weight: 700;
		color: var(--text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.08em;
		text-align: center;
	}

	@media (max-width: 1100px) {
		.dashboard-layout {
			padding-top: 5rem;
		}

		.sidebar {
			display: none;
		}
	}
</style>
