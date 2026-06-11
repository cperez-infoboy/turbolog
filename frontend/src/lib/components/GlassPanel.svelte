<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { HTMLAttributes } from 'svelte/elements';

	interface Props extends HTMLAttributes<HTMLDivElement> {
		padding?: string;
		glow?: boolean;
		selected?: boolean;
		children: Snippet;
	}

	let {
		padding = '2.5rem',
		glow = false,
		selected = false,
		children,
		class: className = '',
		...rest
	}: Props = $props();
</script>

<div
	class="glass-panel {className}"
	class:selected
	class:glow
	style="padding: {padding}"
	{...rest}
>
	{@render children()}
</div>

<style>
	.glass-panel {
		background: var(--glass-bg);
		backdrop-filter: blur(10px);
		-webkit-backdrop-filter: blur(10px);
		border: 1px solid var(--glass-border);
		border-radius: var(--border-radius);
		transition:
			transform var(--transition-speed) ease,
			border-color var(--transition-speed) ease,
			box-shadow var(--transition-speed) ease;
	}

	.glass-panel:hover {
		transform: translateY(-2px);
		border-color: var(--glass-border-hover);
	}

	.glow {
		box-shadow: 0 0 15px rgba(0, 255, 255, 0.1);
	}

	.glow:hover {
		box-shadow: 0 0 20px rgba(0, 255, 255, 0.2);
	}

	.selected {
		border-color: rgba(0, 255, 255, 0.6);
		box-shadow: 0 0 20px rgba(0, 255, 255, 0.15),
			inset 0 0 20px rgba(0, 255, 255, 0.05);
	}

	.selected:hover {
		border-color: rgba(0, 255, 255, 0.7);
		transform: translateY(-2px);
	}
</style>
