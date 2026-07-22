<script lang="ts">
	import { untrack } from 'svelte';
	import { ApiError } from '$lib/api/client';
	import { closeTask } from '$lib/api/tasks';
	import type { Task } from '$lib/api/tasks';
	import type { StatusReportWithSummary } from '$lib/api/status';
	import { createReport, improveStatus, updateReport } from '$lib/api/status';
	import Button from './Button.svelte';

	interface Props {
		task: Task;
		selected?: boolean;
		report?: StatusReportWithSummary | null;
		date?: string;
		finalized?: boolean;
		onclick?: (task: Task) => void;
		onReportSaved?: () => void;
		onTaskClosed?: () => void;
	}

	let {
		task,
		selected = false,
		report = null,
		date = '',
		finalized = false,
		onclick,
		onReportSaved,
		onTaskClosed
	}: Props = $props();

	let content = $state('');
	let saving = $state(false);
	let saveState = $state<'saved' | 'saving' | 'unsaved'>('unsaved');
	// AI status-improvement state.
	let improving = $state(false); // request in flight
	let revealing = $state(false); // typewriter reveal in progress
	let improveError = $state<string | null>(null);
	let revealTimer: ReturnType<typeof setInterval> | undefined; // non-reactive handle
	let closing = $state(false);
	let closeError = $state<string | null>(null);
	let textareaEl: HTMLTextAreaElement | undefined = $state();
	let cardEl: HTMLDivElement | undefined = $state();

	// A single report can be already pushed to JIRA (jira_comment_id set) even if
	// the whole day isn't finalized yet. That report is individually locked;
	// `finalized` locks the entire day.
	const sentToJira = $derived(!!report?.jira_comment_id);

	// Sync content when report changes (runs on mount + whenever report changes).
	// `report` is the only tracked dependency: `revealing` is read via untrack so a
	// reveal finishing never re-triggers this and clobbers the improved text. If the
	// report DOES change mid-reveal (parent refetch), abort the reveal and adopt it.
	$effect(() => {
		if (untrack(() => revealing)) {
			clearInterval(revealTimer);
			revealing = false;
		}
		content = report?.content ?? '';
		saveState = report ? 'saved' : 'unsaved';
	});

	// Cancel any in-flight AI typewriter reveal when the component unmounts.
	$effect(() => {
		return () => clearInterval(revealTimer);
	});

	// Scroll into view when selected
	$effect(() => {
		if (selected && cardEl) {
			// Delay to let the expand animation start
			setTimeout(() => {
				cardEl?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
			}, 150);
		}
	});

	function autoExpand() {
		if (!textareaEl) return;
		textareaEl.style.height = 'auto';
		textareaEl.style.height = textareaEl.scrollHeight + 'px';
	}

	async function handleSave() {
		if (!content.trim()) return;
		saving = true;
		saveState = 'saving';

		try {
			if (report) {
				await updateReport(report.id, content);
			} else {
				await createReport(task.jira_key, date, content);
			}
			saveState = 'saved';
			onReportSaved?.();
		} catch {
			saveState = 'unsaved';
		} finally {
			saving = false;
		}
	}

	function handleInput() {
		// If the user types during the AI typewriter reveal, their edit wins:
		// cancel the in-flight reveal and keep editing from the current content.
		if (revealing) {
			clearInterval(revealTimer);
			revealing = false;
		}
		saveState = 'unsaved';
		autoExpand();
	}

	async function handleImprove() {
		if (!content.trim() || improving || revealing) return;
		improving = true;
		improveError = null;
		try {
			const improved = await improveStatus(task.jira_key, content);
			improving = false;
			typewrite(improved);
		} catch (err) {
			improving = false;
			// Surface the server's message when we have one (e.g. "IA no configurada
			// en el servidor"); fall back to a generic message for network failures.
			improveError =
				err instanceof ApiError && err.message
					? err.message
					: 'No se pudo mejorar el texto. Intenta nuevamente.';
		}
	}

	// Reveal `text` in chunks every 20ms for an "AI is writing" effect. The chunk
	// size scales with text length so the reveal stays ~constant in time instead of
	// crawling through very long outputs. Editing/saving stay disabled for the whole
	// reveal (see the disabled bindings) so we never persist half-revealed text.
	function typewrite(text: string) {
		clearInterval(revealTimer);
		content = '';
		revealing = true;
		autoExpand();
		const chunk = Math.max(2, Math.ceil(text.length / 200));
		let i = 0;
		revealTimer = setInterval(() => {
			i += chunk;
			content = text.slice(0, i);
			autoExpand();
			if (i >= text.length) {
				clearInterval(revealTimer);
				revealing = false;
				saveState = 'unsaved'; // programmatic set does not fire oninput
			}
		}, 20);
	}

	function handleHeaderClick() {
		onclick?.(task);
	}

	async function handleCloseTask() {
		if (closing) return;
		closeError = null;
		if (!confirm(`¿Cerrar la tarea ${task.jira_key} en JIRA? Se marcará como Done.`)) return;
		closing = true;
		try {
			await closeTask(task.jira_key);
			onTaskClosed?.();
		} catch (err) {
			closeError =
				err instanceof ApiError && err.status === 409
					? 'La tarea no se puede cerrar desde su estado actual.'
					: 'No se pudo cerrar la tarea. Intenta nuevamente.';
		} finally {
			closing = false;
		}
	}

	// Format an ISO / YYYY-MM-DD date for display in the es locale. '' on falsy/invalid.
	// JIRA `duedate` is date-only (YYYY-MM-DD); Date parses those as UTC, which drifts
	// one day backward in negative-offset timezones (e.g. UTC-3 shows the 14th for the 15th).
	// Date-only strings (no 'T') are forced to local midnight to avoid the off-by-one.
	function formatDate(iso: string | null | undefined): string {
		if (!iso) return '';
		const d = iso.includes('T') ? new Date(iso) : new Date(`${iso}T00:00:00`);
		if (Number.isNaN(d.getTime())) return '';
		return new Intl.DateTimeFormat('es', {
			day: 'numeric',
			month: 'short',
			year: 'numeric'
		}).format(d);
	}

	// A duedate is overdue when it exists and is strictly before today (day granularity).
	const today = new Date();
	today.setHours(0, 0, 0, 0);
	let isOverdue = $derived(
		!!task.duedate && new Date(task.duedate).getTime() < today.getTime()
	);
	let createdLabel = $derived(formatDate(task.created));
	let duedateLabel = $derived(formatDate(task.duedate));

	// Auto-expand textarea when card becomes selected
	$effect(() => {
		if (selected) {
			setTimeout(autoExpand, 200);
		}
	});

	// Collapsible task description ("Ver más / Ver menos").
	// The description is HTML parsed from JIRA's ADF, so line-clamp (text-only)
	// truncates it unpredictably — we recort by max-height instead. The toggle
	// button only shows when the content actually overflows the collapsed height.
	let descEl: HTMLDivElement | undefined = $state();
	let descExpanded = $state(false);
	let descOverflow = $state(false);

	$effect(() => {
		const isOpen = selected; // re-measure when the card opens/closes
		task.description; // re-measure when the visible task changes
		if (!isOpen) {
			// Reset to collapsed when the card closes, so reopening starts fresh.
			descExpanded = false;
			return;
		}
		if (!descEl) return;
		if (descExpanded) {
			descOverflow = false; // expanded = nothing more to reveal
			return;
		}
		const measure = () => {
			if (descEl) descOverflow = descEl.scrollHeight > descEl.clientHeight + 1;
		};
		measure();
		requestAnimationFrame(measure); // re-measure once layout/fonts settle
	});

	function toggleDesc() {
		descExpanded = !descExpanded;
	}
</script>

<div
	class="task-card {selected ? 'selected' : ''} {report ? 'has-report' : ''}"
	bind:this={cardEl}
>
	<button class="card-header" onclick={handleHeaderClick}>
		<div class="task-row">
			<span class="task-key">{task.jira_key}</span>
			{#if task.priority}
				<span class="priority-dot" title={task.priority}></span>
			{/if}
		</div>
		<p class="task-summary">{task.summary}</p>
		{#if createdLabel || task.duedate !== undefined}
			<div class="task-meta">
				{#if createdLabel}
					<span class="meta-item">Creada: <span class="meta-value">{createdLabel}</span></span>
				{/if}
				<span class="meta-item" class:overdue={isOverdue}>
					Vence:
					<span class="meta-value">
						{duedateLabel || 'Sin vencimiento'}
					</span>
				</span>
			</div>
		{/if}
		<div class="task-footer">
			<span class="status-badge">{task.status}</span>
			{#if report}
				<span class="report-badge">Reportado</span>
			{/if}
			<span class="expand-icon" class:open={selected}>
			</span>
		</div>
	</button>

	<div class="accordion-body" class:expanded={selected}>
		<div class="accordion-inner">
			<div class="card-actions">
				{#if task.browse_url}
					<a class="jira-link" href={task.browse_url} target="_blank" rel="noopener">
						Abrir en JIRA ↗
					</a>
				{/if}
				{#if task.status_category === 'indeterminate'}
					<Button
						variant="danger"
						size="sm"
						onclick={handleCloseTask}
						disabled={closing}
						loading={closing}
					>
						Cerrar tarea
					</Button>
					{#if closeError}
						<span class="improve-error">{closeError}</span>
					{/if}
				{/if}
			</div>
			{#if task.description}
				<div class="description-wrap">
					<div
						class="description-block"
						class:collapsed={!descExpanded}
						bind:this={descEl}
					>
						{@html task.description}
					</div>
					{#if descOverflow}
						<button type="button" class="desc-toggle" onclick={toggleDesc}>
							{descExpanded ? 'Ver menos' : 'Ver más'}
						</button>
					{/if}
				</div>
			{/if}
			{#if task.status_category === 'indeterminate'}
				{#if finalized}
					<div class="readonly-banner">
						<span class="banner-text">Día cerrado</span>
					</div>
					{#if content}
						<div class="readonly-content">{content}</div>
					{:else}
						<p class="pending-notice">Sin estado registrado al cerrar el día.</p>
					{/if}
				{:else if sentToJira}
					<div class="readonly-banner jira-sent">
						<span class="banner-text">Enviado a JIRA</span>
					</div>
					<div class="textarea-wrapper readonly" class:focus={false}>
						<textarea
							bind:this={textareaEl}
							bind:value={content}
							rows="4"
							disabled
							aria-readonly="true"
						></textarea>
					</div>
				{:else}
					<div class="editor-toolbar">
						<Button
							variant="secondary"
							size="sm"
							onclick={handleImprove}
							disabled={!content.trim() || improving || revealing}
							loading={improving}
						>
							✨ Mejorar con IA
						</Button>
						{#if improveError}
							<span class="improve-error">{improveError}</span>
						{/if}
					</div>
					<div
						class="textarea-wrapper"
						class:focus={saveState === 'unsaved'}
						class:ai-working={improving}
					>
						<textarea
							bind:this={textareaEl}
							bind:value={content}
							oninput={handleInput}
							placeholder="Escribe tu actualización de estado..."
							rows="4"
							disabled={improving || revealing}
						></textarea>
					</div>

					<div class="editor-footer">
						<span
							class="save-indicator"
							class:unsaved={saveState === 'unsaved'}
							class:saving={saveState === 'saving'}
							class:saved={saveState === 'saved'}
						>
							{saveState === 'saved'
								? 'Guardado'
								: saveState === 'saving'
									? 'Guardando...'
									: 'Sin guardar'}
						</span>
						<Button
							variant="cta"
							onclick={handleSave}
							disabled={!content.trim() || saving || improving || revealing}
							loading={saving}
						>
							Guardar
						</Button>
					</div>
				{/if}
			{:else}
				<p class="pending-notice">Tarea pendiente — el editor de status estará disponible cuando la tarea esté en curso.</p>
			{/if}
		</div>
	</div>
</div>

<style>
	.task-card {
		display: flex;
		flex-direction: column;
		background: var(--glass-bg);
		backdrop-filter: blur(10px);
		-webkit-backdrop-filter: blur(10px);
		border: 1px solid var(--glass-border);
		border-radius: var(--border-radius);
		overflow: hidden;
		transition:
			border-color var(--transition-speed) ease,
			box-shadow var(--transition-speed) ease;
	}

	.task-card:not(.selected):hover {
		border-color: var(--glass-border-hover);
		box-shadow: 0 0 15px rgba(0, 255, 255, 0.15);
	}

	.selected {
		border-color: rgba(0, 255, 255, 0.6);
		box-shadow:
			0 0 20px rgba(0, 255, 255, 0.15),
			inset 0 0 20px rgba(0, 255, 255, 0.05);
	}

	.card-header {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		background: none;
		border: none;
		cursor: pointer;
		text-align: left;
		width: 100%;
		padding: 1.25rem;
		color: inherit;
		font: inherit;
	}

	.task-row {
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

	.task-meta {
		display: flex;
		flex-wrap: wrap;
		gap: 0.75rem;
		font-family: var(--font-body);
		font-size: 0.75rem;
		color: var(--text-secondary);
		margin-top: 0.1rem;
	}

	.meta-item {
		display: inline-flex;
		align-items: baseline;
		gap: 0.25rem;
	}

	.meta-item .meta-value {
		color: var(--text-primary);
	}

	.meta-item.overdue {
		color: var(--neon-pink);
	}

	.meta-item.overdue .meta-value {
		color: var(--neon-pink);
	}

	.description-block {
		font-family: var(--font-body);
		font-size: 0.85rem;
		color: var(--text-secondary);
		line-height: 1.5;
		padding: 0.75rem;
		background: rgba(0, 0, 0, 0.3);
		border: 1px solid var(--glass-border);
		border-radius: 8px;
		box-sizing: border-box;
		overflow-wrap: anywhere;
	}

	/* Collapsed preview: recort by height (predictable with HTML, unlike line-clamp). */
	.description-block.collapsed {
		max-height: 5.4rem;
		overflow: hidden;
		mask-image: linear-gradient(to bottom, #000 70%, transparent 100%);
		-webkit-mask-image: linear-gradient(to bottom, #000 70%, transparent 100%);
	}

	.description-block :global(p) {
		margin: 0 0 0.5rem;
	}

	.description-block :global(p:last-child) {
		margin-bottom: 0;
	}

	.description-block :global(a) {
		color: var(--neon-cyan);
	}

	.description-block :global(ul),
	.description-block :global(ol) {
		margin: 0 0 0.5rem;
		padding-left: 1.25rem;
	}

	.description-block :global(li) {
		margin: 0 0 0.25rem;
	}

	.description-block :global(code) {
		font-family: monospace;
		background: rgba(0, 0, 0, 0.4);
		padding: 0.1rem 0.35rem;
		border-radius: 4px;
		font-size: 0.8rem;
	}

	.description-block :global(pre) {
		background: rgba(0, 0, 0, 0.4);
		padding: 0.75rem;
		border-radius: 8px;
		overflow-x: auto;
		margin: 0 0 0.5rem;
	}

	.description-block :global(pre code) {
		background: none;
		padding: 0;
	}

	.description-block :global(blockquote) {
		border-left: 3px solid var(--glass-border);
		padding-left: 0.75rem;
		margin: 0 0 0.5rem;
		opacity: 0.85;
	}

	.description-block :global(h1),
	.description-block :global(h2),
	.description-block :global(h3) {
		font-family: var(--font-heading);
		font-size: 0.95rem;
		margin: 0.5rem 0 0.25rem;
	}

	.description-block :global(img) {
		max-width: 100%;
		border-radius: 8px;
	}

	.description-wrap {
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
	}

	.desc-toggle {
		align-self: flex-start;
		background: none;
		border: none;
		padding: 0;
		cursor: pointer;
		font-family: var(--font-body);
		font-size: 0.8rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--neon-cyan);
	}

	.desc-toggle:hover {
		text-decoration: underline;
	}

	.desc-toggle:focus-visible {
		outline: 2px solid var(--neon-cyan);
		outline-offset: 2px;
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

	.expand-icon {
		margin-left: auto;
		width: 0;
		height: 0;
		border-left: 5px solid transparent;
		border-right: 5px solid transparent;
		border-top: 5px solid var(--text-secondary);
		transition: transform var(--transition-speed) ease;
	}

	.expand-icon.open {
		transform: rotate(180deg);
	}

	/* Accordion animation using grid-template-rows */
	.accordion-body {
		display: grid;
		grid-template-rows: 0fr;
		transition: grid-template-rows 0.3s ease;
	}

	.accordion-body.expanded {
		grid-template-rows: 1fr;
	}

	.accordion-inner {
		overflow: hidden;
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		padding: 0 1.25rem;
	}

	.accordion-body.expanded .accordion-inner {
		padding-bottom: 1.25rem;
	}

	.textarea-wrapper {
		border: 1px solid var(--glass-border);
		border-radius: 8px;
		overflow: hidden;
		transition:
			border-color var(--transition-speed) ease,
			box-shadow var(--transition-speed) ease;
	}

	.textarea-wrapper.focus {
		border-color: var(--neon-cyan);
		box-shadow: 0 0 12px rgba(0, 255, 255, 0.15);
	}

	/* AI "thinking" pulse on the editor border while the improve request is in flight. */
	.textarea-wrapper.ai-working {
		animation: ai-pulse 1.2s ease-in-out infinite;
	}

	@keyframes ai-pulse {
		0%,
		100% {
			box-shadow: 0 0 8px rgba(0, 255, 255, 0.12);
			border-color: var(--glass-border);
		}
		50% {
			box-shadow: 0 0 22px rgba(0, 255, 255, 0.55);
			border-color: var(--neon-cyan);
		}
	}

	textarea {
		width: 100%;
		min-height: 120px;
		padding: 1rem;
		background: rgba(0, 0, 0, 0.4);
		color: var(--text-primary);
		font-family: var(--font-body);
		font-size: 1rem;
		line-height: 1.6;
		border: none;
		outline: none;
		resize: none;
	}

	textarea::placeholder {
		color: rgba(255, 255, 255, 0.25);
	}

	.card-actions {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		flex-wrap: wrap;
	}

	.jira-link {
		font-family: var(--font-body);
		font-size: 0.8rem;
		font-weight: 600;
		color: var(--neon-cyan);
		text-decoration: none;
		transition: text-shadow var(--transition-speed) ease;
	}

	.jira-link:hover {
		text-decoration: underline;
		text-shadow: 0 0 8px rgba(0, 255, 255, 0.3);
	}

	.editor-footer {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.editor-toolbar {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		flex-wrap: wrap;
	}

	.improve-error {
		font-family: var(--font-body);
		font-size: 0.75rem;
		color: var(--neon-pink);
	}

	.save-indicator {
		font-family: var(--font-body);
		font-size: 0.8rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.save-indicator.saved {
		color: var(--neon-green);
	}

	.save-indicator.saving {
		color: var(--neon-cyan);
	}

	.save-indicator.unsaved {
		color: var(--text-secondary);
	}

		.pending-notice {
			font-family: var(--font-body);
			font-size: 0.85rem;
			color: var(--text-secondary);
			margin: 0;
			padding: 0.5rem 0;
			opacity: 0.7;
		}

	.readonly-banner {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		font-family: var(--font-heading);
		font-size: 0.75rem;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--neon-cyan);
		background: rgba(0, 255, 255, 0.08);
		border: 1px solid rgba(0, 255, 255, 0.3);
		border-radius: 4px;
		padding: 0.2rem 0.6rem;
		align-self: flex-start;
	}

	.readonly-banner.jira-sent {
		color: var(--neon-green);
		background: rgba(0, 255, 136, 0.08);
		border-color: rgba(0, 255, 136, 0.3);
	}

	.readonly-content {
		font-family: var(--font-body);
		font-size: 1rem;
		line-height: 1.6;
		color: var(--text-primary);
		background: rgba(0, 0, 0, 0.3);
		border: 1px solid var(--glass-border);
		border-radius: 8px;
		padding: 1rem;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		opacity: 0.9;
	}

	.textarea-wrapper.readonly {
		opacity: 0.8;
	}

	.textarea-wrapper.readonly textarea {
		cursor: default;
	}
</style>
