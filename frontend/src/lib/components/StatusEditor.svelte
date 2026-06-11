<script lang="ts">
	import { onMount } from 'svelte';
	import type { Task } from '$lib/api/tasks';
	import type { StatusReport } from '$lib/api/status';
	import { createReport, updateReport } from '$lib/api/status';
	import Button from './Button.svelte';

	interface Props {
		task: Task;
		report: StatusReport | null;
		date: string;
		onSave?: () => void;
	}

	let { task, report, date, onSave }: Props = $props();

	let content = $state(report?.content ?? '');
	let saving = $state(false);
	let saveState = $state<'saved' | 'saving' | 'unsaved'>(
		report ? 'saved' : 'unsaved'
	);
	let textareaEl: HTMLTextAreaElement | undefined = $state();

	// Sync content when report changes
	$effect(() => {
		content = report?.content ?? '';
		saveState = report ? 'saved' : 'unsaved';
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
			onSave?.();
		} catch {
			saveState = 'unsaved';
		} finally {
			saving = false;
		}
	}

	function handleInput() {
		saveState = content.trim() ? 'unsaved' : 'unsaved';
		autoExpand();
	}
</script>

<div class="status-editor">
	<div class="editor-header">
		<span class="task-key">{task.jira_key}</span>
		<span class="task-summary">{task.summary}</span>
	</div>

	<div class="textarea-wrapper" class:focus={saveState === 'unsaved'}>
		<textarea
			bind:this={textareaEl}
			bind:value={content}
			oninput={handleInput}
			placeholder="Write your status update..."
			rows="4"
		></textarea>
	</div>

	<div class="editor-footer">
		<span class="save-indicator" class:unsaved={saveState === 'unsaved'} class:saving={saveState === 'saving'} class:saved={saveState === 'saved'}>
			{saveState === 'saved' ? 'Saved' : saveState === 'saving' ? 'Saving...' : 'Unsaved'}
		</span>
		<Button
			variant="cta"
			onclick={handleSave}
			disabled={!content.trim() || saving}
			loading={saving}
		>
			Save
		</Button>
	</div>
</div>

<style>
	.status-editor {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}

	.editor-header {
		display: flex;
		align-items: baseline;
		gap: 0.75rem;
	}

	.task-key {
		font-family: var(--font-heading);
		font-size: 0.8rem;
		font-weight: 700;
		color: var(--neon-cyan);
		letter-spacing: 0.05em;
	}

	.task-summary {
		font-family: var(--font-body);
		font-size: 0.9rem;
		color: var(--text-secondary);
	}

	.textarea-wrapper {
		border: 1px solid var(--glass-border);
		border-radius: 8px;
		overflow: hidden;
		transition: border-color var(--transition-speed) ease,
			box-shadow var(--transition-speed) ease;
	}

	.textarea-wrapper.focus {
		border-color: var(--neon-cyan);
		box-shadow: 0 0 12px rgba(0, 255, 255, 0.15);
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

	.editor-footer {
		display: flex;
		align-items: center;
		justify-content: space-between;
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
</style>
