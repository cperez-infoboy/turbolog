<script lang="ts">
	import { getGoogleLoginUrl } from '$lib/api/auth';
</script>

<svelte:head>
	<title>Turbolog — Iniciar sesión</title>
</svelte:head>

<div class="login-container">
	<div class="login-card">
		<h1 class="login-title">Turbolog</h1>
		<p class="login-subtitle">Seguimiento de tareas JIRA y reportes de estado diarios</p>
		<a href={getGoogleLoginUrl()} class="login-button">Iniciar sesión con Google</a>
	</div>
</div>

<style>
	.login-container {
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 100vh;
		padding: 2rem;
	}

	.login-card {
		text-align: center;
		max-width: 400px;
		width: 100%;
	}

	.login-title {
		font-size: 2.5rem;
		font-weight: 900;
		letter-spacing: 0.05em;
		margin-bottom: 0.5rem;
	}

	.login-subtitle {
		font-size: 1.1rem;
		color: #999;
		margin-bottom: 2rem;
	}

	.login-button {
		display: inline-block;
		padding: 0.75rem 2rem;
		font-size: 1rem;
		font-weight: 600;
		color: #fff;
		background: linear-gradient(135deg, #00ffff, #0066ff);
		border-radius: 8px;
		text-decoration: none;
		transition:
			transform 0.3s ease,
			box-shadow 0.3s ease;
	}

	.login-button:hover {
		transform: translateY(-2px);
		box-shadow: 0 0 20px rgba(0, 255, 255, 0.4);
	}
</style>
