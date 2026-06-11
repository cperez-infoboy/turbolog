<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { register } from '$lib/api/auth';

	interface GoogleData {
		google_sub: string;
		email: string;
		name: string;
		picture: string | null;
	}

	let googleData: GoogleData | null = $state(null);
	let error = $state('');
	let loading = $state(false);

	onMount(() => {
		const state = page.url.searchParams.get('state');
		if (!state) {
			error = 'Missing registration data. Please try signing in again.';
			return;
		}
		try {
			googleData = JSON.parse(atob(state));
		} catch {
			error = 'Invalid registration data. Please try signing in again.';
		}
	});

	async function handleRegister() {
		if (!googleData) return;
		loading = true;
		error = '';

		try {
			await register(googleData);
			window.location.href = '/';
		} catch (e: unknown) {
			if (e instanceof Error) {
				error = e.message || 'Registration failed';
			} else {
				error = 'Registration failed';
			}
		} finally {
			loading = false;
		}
	}
</script>

<svelte:head>
	<title>Turbolog — Register</title>
</svelte:head>

<div class="register-container">
	<div class="register-card">
		{#if googleData}
			<div class="profile-info">
				{#if googleData.picture}
					<img src={googleData.picture} alt="Profile" class="profile-picture" />
				{/if}
				<h1 class="welcome">Welcome, {googleData.name}!</h1>
				<p class="email">{googleData.email}</p>
			</div>

			<p class="confirmation-text">
				Click below to create your Turbolog account using your Google profile.
			</p>

			<button onclick={handleRegister} disabled={loading} class="register-button">
				{loading ? 'Creating account...' : 'Create Account'}
			</button>

			{#if error}
				<p class="error">{error}</p>
			{/if}
		{:else if error}
			<p class="error">{error}</p>
			<a href="/login" class="back-link">Back to login</a>
		{:else}
			<p>Loading...</p>
		{/if}
	</div>
</div>

<style>
	.register-container {
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 100vh;
		padding: 2rem;
	}

	.register-card {
		text-align: center;
		max-width: 420px;
		width: 100%;
	}

	.profile-info {
		margin-bottom: 1.5rem;
	}

	.profile-picture {
		width: 80px;
		height: 80px;
		border-radius: 50%;
		margin-bottom: 1rem;
	}

	.welcome {
		font-size: 1.75rem;
		font-weight: 700;
		margin-bottom: 0.25rem;
	}

	.email {
		color: #999;
		font-size: 0.95rem;
	}

	.confirmation-text {
		color: #ccc;
		margin-bottom: 1.5rem;
	}

	.register-button {
		display: inline-block;
		padding: 0.75rem 2rem;
		font-size: 1rem;
		font-weight: 600;
		color: #fff;
		background: linear-gradient(135deg, #00ffff, #0066ff);
		border: none;
		border-radius: 8px;
		cursor: pointer;
		transition:
			transform 0.3s ease,
			box-shadow 0.3s ease;
	}

	.register-button:hover:not(:disabled) {
		transform: translateY(-2px);
		box-shadow: 0 0 20px rgba(0, 255, 255, 0.4);
	}

	.register-button:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}

	.error {
		color: #ff4444;
		margin-top: 1rem;
	}

	.back-link {
		display: inline-block;
		margin-top: 1rem;
		color: #00cccc;
		text-decoration: none;
	}

	.back-link:hover {
		text-decoration: underline;
	}
</style>
