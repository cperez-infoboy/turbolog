<script lang="ts">
	import { onMount } from 'svelte';
	import { getAuthState } from '$lib/stores/auth.svelte';
	import { ApiError } from '$lib/api/client';
	import {
		getAuditUsers,
		updateUserFlags,
		runReminders,
		getAllowedEmails,
		addAllowedEmail,
		removeAllowedEmail
	} from '$lib/api/audit';
	import type { AuditUser, AllowedEmail } from '$lib/api/audit';
	import GlassPanel from '$lib/components/GlassPanel.svelte';
	import Button from '$lib/components/Button.svelte';
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';

	const auth = getAuthState();

	let users = $state<AuditUser[]>([]);
	let allowedEmails = $state<AllowedEmail[]>([]);
	let loading = $state(true);
	let loadError = $state<string | null>(null);

	// Allowed-emails form state.
	let newEmail = $state('');
	let addingEmail = $state(false);
	let emailError = $state<string | null>(null);

	// Reminders state.
	let sendingReminders = $state(false);
	let remindersMsg = $state<string | null>(null);
	let remindersError = $state<string | null>(null);

	// Per-user busy/error map keyed by user id (avoids clobbering the list while
	// a single PATCH is in flight). Error messages are short-lived: clearing on
	// the next interaction keeps the UI calm.
	let userErrors = $state<Record<string, string>>({});

	// Non-seed admins: the set that can actually be demoted. Used to lock the
	// last remaining one so the panel can never strip every manageable admin.
	const lastNonSeedAdmins = $derived(
		users.filter((u) => u.is_admin && !u.is_seed)
	);

	function adminToggleLocked(user: AuditUser): {
		disabled: boolean;
		title: string;
	} {
		if (user.is_seed) {
			return { disabled: true, title: 'Administrador .env (inmutable)' };
		}
		if (user.is_admin && lastNonSeedAdmins.length <= 1) {
			return { disabled: true, title: 'No se puede quitar el último administrador' };
		}
		return { disabled: false, title: '' };
	}

	// Admin guard: bounce non-admins out before any data fetch matters.
	$effect(() => {
		if (auth.authLoaded && !auth.isAdmin) {
			window.location.href = '/';
		}
	});

	onMount(async () => {
		await loadAll();
	});

	async function loadAll() {
		loading = true;
		loadError = null;
		try {
			const [u, e] = await Promise.all([getAuditUsers(), getAllowedEmails()]);
			users = u;
			allowedEmails = e;
		} catch {
			loadError = 'No se pudieron cargar los datos.';
		} finally {
			loading = false;
		}
	}

	async function handleAddEmail() {
		const trimmed = newEmail.trim();
		if (!trimmed || addingEmail) return;
		addingEmail = true;
		emailError = null;
		try {
			await addAllowedEmail(trimmed);
			newEmail = '';
			allowedEmails = await getAllowedEmails();
		} catch (err) {
			emailError = errorMessage(err);
		} finally {
			addingEmail = false;
		}
	}

	async function handleRemoveEmail(email: string) {
		if (!confirm(`¿Quitar "${email}"? Su próximo inicio de sesión será bloqueado.`))
			return;
		try {
			await removeAllowedEmail(email);
			allowedEmails = allowedEmails.filter((e) => e.email !== email);
		} catch (err) {
			emailError = errorMessage(err);
		}
	}

	async function handleToggle(user: AuditUser, field: 'is_admin' | 'is_audited') {
		// Optimistic flip: mutate local state immediately, revert on failure.
		const prev = user[field];
		const next = !prev;
		const idx = users.findIndex((u) => u.id === user.id);
		if (idx === -1) return;

		users[idx] = { ...users[idx], [field]: next };
		userErrors[user.id] = '';

		try {
			const updated = await updateUserFlags(user.id, { [field]: next });
			users[idx] = updated;
		} catch (err) {
			// Revert to the prior value — the server is the source of truth.
			users[idx] = { ...users[idx], [field]: prev };
			if (err instanceof ApiError && err.status === 409) {
				userErrors[user.id] = 'No se puede quitar el último administrador.';
			} else {
				userErrors[user.id] = errorMessage(err);
			}
		}
	}

	async function handleRunReminders() {
		if (sendingReminders) return;
		sendingReminders = true;
		remindersMsg = null;
		remindersError = null;
		try {
			await runReminders();
			remindersMsg = 'Recordatorios enviados.';
		} catch (err) {
			remindersError = errorMessage(err);
		} finally {
			sendingReminders = false;
		}
	}

	function errorMessage(err: unknown): string {
		if (err instanceof ApiError && err.message) return err.message;
		return 'Ocurrió un error. Intenta nuevamente.';
	}
</script>

<svelte:head>
	<title>Turbolog — Administración</title>
</svelte:head>

<div class="admin-page">
	<h1 class="page-title">Administración</h1>

	{#if auth.authLoaded && !auth.isAdmin}
		<p class="msg">Redirigiendo...</p>
	{:else if loading}
		<LoadingSpinner />
	{:else if loadError}
		<p class="msg error">{loadError}</p>
		<Button variant="secondary" onclick={loadAll}>Reintentar</Button>
	{:else}
		<!-- Acceso a la plataforma -->
		<GlassPanel padding="1.75rem">
			<h2 class="section-title">Acceso a la plataforma</h2>
			<p class="section-hint">
				Los correos en esta lista pueden iniciar sesión. Quitar uno bloquea su próximo
				ingreso.
			</p>

			<form class="email-form" onsubmit={(e) => { e.preventDefault(); handleAddEmail(); }}>
				<input
					type="email"
					bind:value={newEmail}
					placeholder="correo@ejemplo.com"
					disabled={addingEmail}
					required
				/>
				<Button type="submit" variant="cta" loading={addingEmail} disabled={addingEmail}>
					Agregar
				</Button>
			</form>

			{#if emailError}
				<p class="msg error">{emailError}</p>
			{/if}

			{#if allowedEmails.length === 0}
				<p class="empty">Sin correos autorizados.</p>
			{:else}
				<ul class="email-list">
					{#each allowedEmails as entry (entry.email)}
						<li class="email-row" class:disabled={entry.is_seed || entry.email === auth.user?.email}>
							<span class="email-text">
								{entry.email}
								{#if entry.is_seed}<span class="seed-badge">Seed</span>{/if}
							</span>
							<Button
								variant="danger"
								size="sm"
								disabled={entry.is_seed || entry.email === auth.user?.email}
								title={entry.is_seed
									? 'Administrador .env (inmutable)'
									: entry.email === auth.user?.email
										? 'Es tu propio correo'
										: ''}
								onclick={() => handleRemoveEmail(entry.email)}
							>
								Quitar
							</Button>
						</li>
					{/each}
				</ul>
			{/if}
		</GlassPanel>

		<!-- Gestión de usuarios -->
		<GlassPanel padding="1.75rem">
			<h2 class="section-title">Gestión de usuarios</h2>

			{#if users.length === 0}
				<p class="empty">No hay usuarios registrados.</p>
			{:else}
				<ul class="user-list">
					{#each users as user (user.id)}
						<li class="user-row">
							<div class="user-info">
								<span class="user-name">
									{user.name || 'Sin nombre'}
									{#if user.is_seed}<span class="seed-badge">Seed</span>{/if}
								</span>
								<span class="user-email">{user.email}</span>
								{#if userErrors[user.id]}
									<span class="user-error">{userErrors[user.id]}</span>
								{/if}
							</div>
							<div class="toggles">
								<label class="toggle">
									<span class="toggle-label">Auditado</span>
									<input
										type="checkbox"
										checked={user.is_audited}
										onchange={() => handleToggle(user, 'is_audited')}
									/>
									<span class="toggle-track" class:on={user.is_audited}></span>
								</label>
								<label
									class="toggle"
									class:disabled={adminToggleLocked(user).disabled}
									title={adminToggleLocked(user).title}
								>
									<span class="toggle-label">Admin</span>
									<input
										type="checkbox"
										checked={user.is_admin}
										disabled={adminToggleLocked(user).disabled}
										onchange={() => handleToggle(user, 'is_admin')}
									/>
									<span class="toggle-track" class:on={user.is_admin}></span>
								</label>
							</div>
						</li>
					{/each}
				</ul>
			{/if}
		</GlassPanel>

		<!-- Recordatorios -->
		<GlassPanel padding="1.75rem">
			<h2 class="section-title">Recordatorios</h2>
			<p class="section-hint">
				Envía un recordatorio manual a los usuarios auditados que aún no reportaron hoy.
			</p>
			<Button
				variant="cta"
				onclick={handleRunReminders}
				loading={sendingReminders}
				disabled={sendingReminders}
			>
				Enviar recordatorios ahora
			</Button>
			{#if remindersMsg}
				<p class="msg success">{remindersMsg}</p>
			{/if}
			{#if remindersError}
				<p class="msg error">{remindersError}</p>
			{/if}
		</GlassPanel>
	{/if}
</div>

<style>
	.admin-page {
		display: flex;
		flex-direction: column;
		gap: 1.5rem;
		padding: 6rem 5% 2rem;
		max-width: 900px;
		margin: 0 auto;
		min-height: 100vh;
	}

	.page-title {
		font-size: 1.6rem;
		letter-spacing: 0.05em;
	}

	.section-title {
		font-size: 1.05rem;
		margin: 0 0 0.5rem;
		letter-spacing: 0.04em;
	}

	.section-hint {
		font-family: var(--font-body);
		font-size: 0.85rem;
		color: var(--text-secondary);
		margin: 0 0 1rem;
		opacity: 0.85;
	}

	.email-form {
		display: flex;
		gap: 0.75rem;
		flex-wrap: wrap;
	}

	.email-form input {
		flex: 1;
		min-width: 200px;
		background: rgba(0, 0, 0, 0.4);
		border: 1px solid var(--glass-border);
		border-radius: 8px;
		padding: 0.6rem 1rem;
		color: var(--text-primary);
		font-family: var(--font-body);
		font-size: 1rem;
		outline: none;
		transition: border-color var(--transition-speed) ease;
	}

	.email-form input:focus {
		border-color: var(--neon-cyan);
	}

	.email-list,
	.user-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.email-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
		padding: 0.6rem 0.75rem;
		background: rgba(0, 0, 0, 0.3);
		border: 1px solid var(--glass-border);
		border-radius: 8px;
	}

	.email-text {
		font-family: var(--font-body);
		font-size: 0.95rem;
		color: var(--text-primary);
		word-break: break-all;
	}

	.user-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
		padding: 0.75rem;
		background: rgba(0, 0, 0, 0.3);
		border: 1px solid var(--glass-border);
		border-radius: 8px;
		flex-wrap: wrap;
	}

	.user-info {
		display: flex;
		flex-direction: column;
		gap: 0.1rem;
	}

	.user-name {
		font-family: var(--font-body);
		font-size: 0.95rem;
		font-weight: 600;
		color: var(--text-primary);
	}

	.user-email {
		font-family: var(--font-body);
		font-size: 0.8rem;
		color: var(--text-secondary);
	}

	.user-error {
		font-family: var(--font-body);
		font-size: 0.78rem;
		color: var(--neon-pink);
		margin-top: 0.2rem;
	}

	.toggles {
		display: flex;
		gap: 1.25rem;
		align-items: center;
	}

	.toggle {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		cursor: pointer;
		user-select: none;
	}

	.toggle-label {
		font-family: var(--font-body);
		font-size: 0.8rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--text-secondary);
	}

	.toggle input {
		position: absolute;
		opacity: 0;
		width: 0;
		height: 0;
	}

	.toggle-track {
		position: relative;
		width: 38px;
		height: 20px;
		border-radius: 20px;
		background: rgba(255, 255, 255, 0.12);
		border: 1px solid var(--glass-border);
		transition:
			background var(--transition-speed) ease,
			border-color var(--transition-speed) ease,
			box-shadow var(--transition-speed) ease;
	}

	.toggle-track::after {
		content: '';
		position: absolute;
		top: 2px;
		left: 2px;
		width: 14px;
		height: 14px;
		border-radius: 50%;
		background: var(--text-secondary);
		transition:
			transform var(--transition-speed) ease,
			background var(--transition-speed) ease;
	}

	.toggle-track.on {
		background: rgba(0, 255, 255, 0.25);
		border-color: var(--neon-cyan);
		box-shadow: 0 0 8px rgba(0, 255, 255, 0.3);
	}

	.toggle-track.on::after {
		transform: translateX(18px);
		background: var(--neon-cyan);
	}

	.toggle input:focus-visible + .toggle-track {
		outline: 2px solid var(--neon-cyan);
		outline-offset: 2px;
	}

	.toggle.disabled {
		opacity: 0.45;
		cursor: not-allowed;
	}

	.toggle.disabled .toggle-track.on {
		box-shadow: none;
		filter: grayscale(0.4);
	}

	.seed-badge {
		display: inline-block;
		margin-left: 0.4rem;
		padding: 0.05rem 0.4rem;
		font-family: var(--font-body);
		font-size: 0.65rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--neon-cyan);
		border: 1px solid var(--neon-cyan);
		border-radius: 4px;
		vertical-align: middle;
	}

	.email-row.disabled {
		opacity: 0.55;
	}

	.email-row.disabled :global(button) {
		cursor: not-allowed;
		filter: grayscale(0.5);
	}

	.empty {
		font-family: var(--font-body);
		font-size: 0.9rem;
		color: var(--text-secondary);
		opacity: 0.7;
		margin: 0;
	}

	.msg {
		font-family: var(--font-body);
		font-size: 0.9rem;
		font-weight: 600;
		padding: 0.5rem 0.75rem;
		border-radius: 8px;
		border: 1px solid var(--glass-border);
		margin: 0.75rem 0 0;
	}

	.msg.success {
		color: var(--neon-green);
		background: rgba(0, 255, 136, 0.08);
		border-color: rgba(0, 255, 136, 0.3);
	}

	.msg.error {
		color: var(--neon-pink);
		background: rgba(255, 0, 255, 0.08);
		border-color: rgba(255, 0, 0, 0.3);
	}

	@media (max-width: 900px) {
		.admin-page {
			padding-top: 5rem;
		}
	}
</style>
