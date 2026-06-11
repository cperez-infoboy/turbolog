<script lang="ts">
	import Button from './Button.svelte';

	interface UserInfo {
		id: string;
		email: string;
		name: string;
		picture: string | null;
	}

	interface Props {
		user: UserInfo | null;
		onlogout?: () => void;
	}

	let { user, onlogout }: Props = $props();
</script>

<header class="site-header">
	<nav class="nav">
		<a href="/" class="logo">TURBOLOG</a>

		<div class="nav-links">
			<a href="/" class="nav-link">Dashboard</a>
			<a href="/settings" class="nav-link">Settings</a>
		</div>

		<div class="user-menu">
			{#if user}
				<span class="user-name">{user.name}</span>
				<Button variant="secondary" onclick={onlogout}>Logout</Button>
			{/if}
		</div>
	</nav>
</header>

<style>
	.site-header {
		position: fixed;
		top: 0;
		left: 0;
		right: 0;
		z-index: 100;
		background: rgba(0, 0, 0, 0.8);
		backdrop-filter: blur(10px);
		-webkit-backdrop-filter: blur(10px);
		border-bottom: 1px solid var(--glass-border);
		padding: 0 2rem;
	}

	.nav {
		display: flex;
		align-items: center;
		justify-content: space-between;
		height: 64px;
		max-width: 1400px;
		margin: 0 auto;
	}

	.logo {
		font-family: var(--font-heading);
		font-size: 1.25rem;
		font-weight: 900;
		color: var(--neon-cyan);
		text-shadow:
			0 0 5px rgba(0, 255, 255, 0.5),
			0 0 10px rgba(0, 255, 255, 0.3);
		letter-spacing: 0.1em;
	}

	.logo:hover {
		color: var(--text-primary);
		text-shadow:
			0 0 5px rgba(0, 255, 255, 0.7),
			0 0 10px rgba(0, 255, 255, 0.5);
	}

	.nav-links {
		display: flex;
		gap: 1.5rem;
	}

	.nav-link {
		font-family: var(--font-body);
		font-size: 1rem;
		font-weight: 600;
		color: var(--text-secondary);
		transition: color var(--transition-speed) ease;
	}

	.nav-link:hover {
		color: var(--neon-cyan);
	}

	.user-menu {
		display: flex;
		align-items: center;
		gap: 1rem;
	}

	.user-name {
		font-family: var(--font-body);
		font-size: 0.95rem;
		color: var(--text-secondary);
	}
</style>
