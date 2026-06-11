<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { HTMLAttributes } from 'svelte/elements';

	interface Props extends HTMLAttributes<HTMLButtonElement> {
		variant?: 'cta' | 'secondary' | 'danger';
		disabled?: boolean;
		loading?: boolean;
		type?: 'button' | 'submit' | 'reset';
		onclick?: (e: MouseEvent) => void;
		children?: Snippet;
	}

	let {
		variant = 'cta',
		disabled = false,
		loading = false,
		type = 'button',
		onclick,
		children,
		class: className = '',
		...rest
	}: Props = $props();
</script>

<button
	class="btn btn-{variant} {className}"
	{type}
	{disabled}
	{onclick}
	class:loading
	{...rest}
>
	{#if loading}
		<span class="spinner"></span>
	{/if}
	{#if children}
		{@render children()}
	{/if}
</button>

<style>
	.btn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: 0.5rem;
		padding: 0.75rem 1.5rem;
		font-family: var(--font-heading);
		font-size: 0.875rem;
		font-weight: 700;
		letter-spacing: 0.05em;
		text-transform: uppercase;
		border: none;
		border-radius: 8px;
		cursor: pointer;
		transition:
			transform var(--transition-speed) ease,
			box-shadow var(--transition-speed) ease,
			background var(--transition-speed) ease,
			border-color var(--transition-speed) ease,
			opacity var(--transition-speed) ease;
	}

	.btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	/* CTA variant */
	.btn-cta {
		background: linear-gradient(135deg, var(--neon-cyan), var(--neon-blue));
		color: var(--dark-bg);
	}

	.btn-cta:hover:not(:disabled) {
		transform: translateY(-2px);
		box-shadow: 0 0 20px rgba(0, 255, 255, 0.4);
	}

	.btn-cta:active:not(:disabled) {
		transform: translateY(0);
	}

	/* Secondary variant */
	.btn-secondary {
		background: transparent;
		color: var(--neon-cyan);
		border: 1px solid var(--neon-cyan);
	}

	.btn-secondary:hover:not(:disabled) {
		background: rgba(0, 255, 255, 0.1);
		transform: translateY(-2px);
		box-shadow: 0 0 15px rgba(0, 255, 255, 0.2);
	}

	.btn-secondary:active:not(:disabled) {
		transform: translateY(0);
	}

	/* Danger variant */
	.btn-danger {
		background: rgba(255, 50, 50, 0.15);
		color: #ff5050;
		border: 1px solid rgba(255, 50, 50, 0.4);
	}

	.btn-danger:hover:not(:disabled) {
		background: rgba(255, 50, 50, 0.25);
		transform: translateY(-2px);
		box-shadow: 0 0 15px rgba(255, 50, 50, 0.2);
	}

	.btn-danger:active:not(:disabled) {
		transform: translateY(0);
	}

	/* Loading spinner */
	.spinner {
		width: 1rem;
		height: 1rem;
		border: 2px solid transparent;
		border-top-color: currentColor;
		border-radius: 50%;
		animation: spin 0.6s linear infinite;
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	.loading {
		pointer-events: none;
	}
</style>
