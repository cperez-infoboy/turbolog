<script lang="ts">
	type HeadingTag = 'h1' | 'h2' | 'h3' | 'h4';

	interface Props {
		tag?: HeadingTag;
		text: string;
		class?: string;
	}

	let { tag = 'h2', text, class: className = '' }: Props = $props();
</script>

{#if tag === 'h1'}
	<h1 class="neon-text {className}">{text}</h1>
{:else if tag === 'h2'}
	<h2 class="neon-text {className}">{text}</h2>
{:else if tag === 'h3'}
	<h3 class="neon-text {className}">{text}</h3>
{:else}
	<h4 class="neon-text {className}">{text}</h4>
{/if}

<style>
	.neon-text {
		font-family: var(--font-heading);
		color: var(--text-primary);
		text-shadow:
			0 0 7px var(--neon-cyan),
			0 0 10px var(--neon-cyan),
			0 0 21px var(--neon-cyan),
			0 0 42px var(--neon-blue);
	}
</style>
