<script lang="ts">
	import { getGoogleLoginUrl } from '$lib/api/auth';
	import { logout } from '$lib/stores/auth.svelte';
	import Button from '$lib/components/Button.svelte';

	let loggingOut = $state(false);

	async function handleLogout() {
		if (loggingOut) return;
		loggingOut = true;
		await logout();
	}
</script>

<svelte:head>
	<title>Turbolog — Sin acceso</title>
</svelte:head>

<div class="no-access">
	<div class="no-access-card">
		<h1 class="no-access-title">Acceso denegado</h1>
		<p class="no-access-message">
			Tu correo no está autorizado para ingresar. Contactá a un administrador.
		</p>
		<div class="no-access-actions">
			<a href={getGoogleLoginUrl()}>
				<Button variant="cta">Reintentar</Button>
			</a>
			<Button
				variant="secondary"
				onclick={handleLogout}
				loading={loggingOut}
				disabled={loggingOut}
			>
				Cerrar sesión
			</Button>
		</div>
	</div>
</div>

<style>
	.no-access {
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 100vh;
		padding: 2rem;
	}

	.no-access-card {
		text-align: center;
		max-width: 440px;
		width: 100%;
		background: var(--glass-bg);
		backdrop-filter: blur(10px);
		-webkit-backdrop-filter: blur(10px);
		border: 1px solid var(--glass-border);
		border-radius: var(--border-radius);
		padding: 2.5rem 2rem;
	}

	.no-access-title {
		font-size: 1.5rem;
		color: var(--neon-pink);
		letter-spacing: 0.05em;
		margin: 0 0 1rem;
		text-shadow: 0 0 10px rgba(255, 0, 255, 0.3);
	}

	.no-access-message {
		font-family: var(--font-body);
		font-size: 1rem;
		color: var(--text-secondary);
		line-height: 1.6;
		margin: 0 0 1.75rem;
	}

	.no-access-actions {
		display: flex;
		gap: 0.75rem;
		justify-content: center;
		flex-wrap: wrap;
	}

	.no-access-actions :global(.btn) {
		text-decoration: none;
	}
</style>
