<script lang="ts">
	import { onMount } from 'svelte';
	import GlassPanel from '$lib/components/GlassPanel.svelte';
	import Button from '$lib/components/Button.svelte';
	import NeonText from '$lib/components/NeonText.svelte';
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
	import {
		getJiraConnectionState,
		checkConnection,
		connect,
		disconnect
	} from '$lib/stores/jira-connection.svelte';

	const jira = getJiraConnectionState();

	let email = $state('');
	let token = $state('');
	let domain = $state('');
	let pageLoading = $state(true);

	onMount(async () => {
		await checkConnection();
		pageLoading = false;
	});

	async function handleConnect() {
		try {
			await connect(email, token, domain);
			email = '';
			token = '';
			domain = '';
		} catch {
			// error is set in the store
		}
	}

	async function handleDisconnect() {
		try {
			await disconnect();
		} catch {
			// error is set in the store
		}
	}
</script>

<div class="settings-page">
	<NeonText tag="h1" text="Settings" />

	<GlassPanel>
		<h2 class="section-title">JIRA Connection</h2>

		{#if pageLoading}
			<LoadingSpinner />
		{:else if jira.connected}
			<div class="connection-info">
				<div class="info-row">
					<span class="label">Email:</span>
					<span class="value">{jira.jiraEmail}</span>
				</div>
				<div class="info-row">
					<span class="label">Status:</span>
					<span class="value status-connected">Connected</span>
				</div>

				<div class="actions">
					<Button variant="danger" onclick={handleDisconnect} loading={jira.loading}>
						Disconnect
					</Button>
				</div>
			</div>
		{:else}
			<form class="connect-form" onsubmit={(e) => { e.preventDefault(); handleConnect(); }}>
				<div class="form-group">
					<label for="jira-email">JIRA Email</label>
					<input
						id="jira-email"
						type="email"
						bind:value={email}
						placeholder="you@company.com"
						required
					/>
				</div>

				<div class="form-group">
					<label for="jira-token">API Token</label>
					<input
						id="jira-token"
						type="password"
						bind:value={token}
						placeholder="Your JIRA API token"
						required
					/>
				</div>

				<div class="form-group">
					<label for="jira-domain">JIRA Domain</label>
					<input
						id="jira-domain"
						type="text"
						bind:value={domain}
						placeholder="yourcompany.atlassian.net"
						required
					/>
				</div>

				{#if jira.error}
					<p class="error">{jira.error}</p>
				{/if}

				<Button type="submit" variant="cta" disabled={!email || !token || !domain} loading={jira.loading}>
					Connect JIRA
				</Button>
			</form>
		{/if}
	</GlassPanel>
</div>

<style>
	.settings-page {
		max-width: 700px;
		margin: 80px auto 0;
		padding: 0 1.5rem;
	}

	.section-title {
		font-family: var(--font-heading);
		font-size: 1.1rem;
		color: var(--neon-cyan);
		margin-bottom: 1.5rem;
	}

	/* Connection info */
	.connection-info {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}

	.info-row {
		display: flex;
		gap: 0.5rem;
		font-family: var(--font-body);
		font-size: 1rem;
	}

	.label {
		color: var(--text-secondary);
		min-width: 80px;
	}

	.value {
		color: var(--text-primary);
	}

	.status-connected {
		color: var(--neon-green);
	}

	.actions {
		margin-top: 1rem;
	}

	/* Form */
	.connect-form {
		display: flex;
		flex-direction: column;
		gap: 1.25rem;
	}

	.form-group {
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
	}

	.form-group label {
		font-family: var(--font-body);
		font-size: 0.9rem;
		color: var(--text-secondary);
	}

	.form-group input {
		background: rgba(0, 0, 0, 0.5);
		border: 1px solid var(--glass-border);
		border-radius: 8px;
		padding: 0.7rem 1rem;
		color: var(--text-primary);
		font-family: var(--font-body);
		font-size: 1rem;
		transition: border-color var(--transition-speed) ease;
		outline: none;
	}

	.form-group input:focus {
		border-color: var(--neon-cyan);
		box-shadow: 0 0 8px rgba(0, 255, 255, 0.15);
	}

	.form-group input::placeholder {
		color: rgba(255, 255, 255, 0.3);
	}

	.error {
		color: #ff5050;
		font-family: var(--font-body);
		font-size: 0.9rem;
		margin: 0;
	}
</style>
