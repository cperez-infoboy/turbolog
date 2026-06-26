<script lang="ts">
	interface Props {
		reported: number;
		expected: number;
		size?: number;
		strokeWidth?: number;
		showLabel?: boolean;
	}

	let { reported, expected, size = 120, strokeWidth = 10, showLabel = true }: Props = $props();

	const radius = $derived((size - strokeWidth) / 2);
	const circumference = $derived(2 * Math.PI * radius);
	const percentage = $derived(expected > 0 ? Math.round((reported / expected) * 100) : 0);
	const filled = $derived(circumference * (percentage / 100));
	const offset = $derived(circumference / 4);

	const gaugeColor = $derived.by(() => {
		if (percentage >= 80) return 'var(--neon-green)';
		if (percentage >= 50) return 'var(--neon-cyan)';
		return 'var(--neon-pink)';
	});

	const center = $derived(size / 2);
	const hasData = $derived(expected > 0);
	const fontSize = $derived(Math.max(size * 0.2, 7));
</script>

<div class="gauge-wrapper">
	<svg width={size} height={size} viewBox="0 0 {size} {size}" role="img" aria-label="Cumplimiento: {percentage}%">
		<circle
			cx={center}
			cy={center}
			r={radius}
			fill="none"
			stroke="var(--glass-border)"
			stroke-width={strokeWidth}
		/>
		<circle
			cx={center}
			cy={center}
			r={radius}
			fill="none"
			stroke={gaugeColor}
			stroke-width={strokeWidth}
			stroke-linecap="round"
			stroke-dasharray="{filled} {circumference - filled}"
			stroke-dashoffset={offset}
			class="gauge-fill"
		/>
		<text
			x={center}
			y={center}
			text-anchor="middle"
			dominant-baseline="central"
			class="gauge-text"
			font-size={fontSize}
		>
			{hasData ? `${percentage}%` : 'Sin datos'}
		</text>
	</svg>
	{#if showLabel && hasData}
		<p class="gauge-label">{reported} de {expected} días</p>
	{/if}
</div>

<style>
	.gauge-wrapper {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.5rem;
	}

	.gauge-fill {
		transition: stroke-dasharray 0.4s ease, stroke 0.4s ease;
	}

	.gauge-text {
		font-family: var(--font-heading);
		font-weight: 700;
		fill: var(--text-primary);
	}

	.gauge-label {
		font-family: var(--font-body);
		font-size: 0.85rem;
		color: var(--text-secondary);
		margin: 0;
	}
</style>
