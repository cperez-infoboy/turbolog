<script lang="ts">
	import { onMount } from 'svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import { getAuthState } from '$lib/stores/auth.svelte';
	import { getMonthlyAudit, getAuditUsers, getUserMonthlyAudit } from '$lib/api/audit';
	import type { UserMonthAudit, UserDetailAudit, AuditUser } from '$lib/api/audit';
	import GlassPanel from '$lib/components/GlassPanel.svelte';
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
	import Button from '$lib/components/Button.svelte';
	import ComplianceGauge from '$lib/components/ComplianceGauge.svelte';

	const auth = getAuthState();

	// Default month picker value: current "YYYY-MM".
	function currentMonth(): string {
		const d = new Date();
		const m = String(d.getMonth() + 1).padStart(2, '0');
		return `${d.getFullYear()}-${m}`;
	}

	let month = $state(currentMonth());
	let rows = $state<UserMonthAudit[]>([]);
	let loading = $state(false);
	let error = $state<string | null>(null);
	// Expanded falta_dates panels keyed by user_id.
	let expanded = $state<SvelteSet<string>>(new SvelteSet());

	// User selector state.
	let auditedUsers = $state<AuditUser[]>([]);
	let selectedUserId = $state<string>('');
	let userDetail = $state<UserDetailAudit | null>(null);
	let userDetailLoading = $state(false);
	let userDetailError = $state<string | null>(null);

	const selectedUser = $derived(
		auditedUsers.find((u) => u.id === selectedUserId) ?? null
	);

	$effect(() => {
		if (auth.authLoaded && !auth.isAdmin) {
			window.location.href = '/';
		}
	});

	onMount(async () => {
		await loadAuditedUsers();
		await loadAudit();
	});

	async function loadAuditedUsers() {
		try {
			const allUsers = await getAuditUsers();
			auditedUsers = allUsers
				.filter((u) => u.is_audited)
				.sort((a, b) => a.email.localeCompare(b.email));
		} catch {
			// Non-critical — dropdown will be empty.
		}
	}

	async function loadAudit() {
		const [yearStr, monthStr] = month.split('-');
		const year = Number(yearStr);
		const m = Number(monthStr);
		if (!year || !m) return;
		loading = true;
		error = null;
		try {
			rows = await getMonthlyAudit(year, m);
		} catch {
			error = 'No se pudo cargar el reporte mensual.';
			rows = [];
		} finally {
			loading = false;
		}
	}

	async function loadUserDetail() {
		if (!selectedUserId) {
			userDetail = null;
			userDetailError = null;
			return;
		}
		const [yearStr, monthStr] = month.split('-');
		const year = Number(yearStr);
		const m = Number(monthStr);
		if (!year || !m) return;
		userDetailLoading = true;
		userDetailError = null;
		try {
			userDetail = await getUserMonthlyAudit(selectedUserId, year, m);
		} catch {
			userDetailError = 'No se pudo cargar el detalle del usuario.';
			userDetail = null;
		} finally {
			userDetailLoading = false;
		}
	}

	function handleMonthChange() {
		expanded = new SvelteSet();
		if (selectedUserId) {
			loadUserDetail();
		} else {
			loadAudit();
		}
	}

	function handleUserChange() {
		expanded = new SvelteSet();
		if (selectedUserId) {
			loadUserDetail();
		} else {
			userDetail = null;
			userDetailError = null;
			loadAudit();
		}
	}

	function toggleFaltas(userId: string) {
		if (expanded.has(userId)) {
			expanded.delete(userId);
		} else {
			expanded.add(userId);
		}
	}

	function formatDate(iso: string): string {
		// falta_dates come as date-only (YYYY-MM-DD); force local midnight to
		// avoid the UTC off-by-one seen elsewhere in the app.
		const d = iso.includes('T') ? new Date(iso) : new Date(`${iso}T00:00:00`);
		if (Number.isNaN(d.getTime())) return iso;
		return new Intl.DateTimeFormat('es', {
			day: 'numeric',
			month: 'short'
		}).format(d);
	}
</script>

<svelte:head>
	<title>Turbolog — Auditoría</title>
</svelte:head>

<div class="audit-page">
	<h1 class="page-title">Auditoría mensual</h1>

	{#if auth.authLoaded && !auth.isAdmin}
		<p class="msg">Redirigiendo...</p>
	{:else}
		<div class="controls-bar">
			<div class="control-group">
				<label for="audit-month">Mes</label>
				<input
					id="audit-month"
					type="month"
					bind:value={month}
					onchange={handleMonthChange}
				/>
			</div>
			<div class="control-group">
				<label for="audit-user">Usuario</label>
				<select id="audit-user" bind:value={selectedUserId} onchange={handleUserChange}>
					<option value="">Todos los usuarios</option>
					{#each auditedUsers as user (user.id)}
						<option value={user.id}>{user.email}</option>
					{/each}
				</select>
			</div>
		</div>

		{#if selectedUserId}
			<!-- Per-user detail view -->
			{#if userDetailLoading}
				<LoadingSpinner />
			{:else if userDetailError}
				<p class="msg error">{userDetailError}</p>
				<Button variant="secondary" onclick={loadUserDetail}>Reintentar</Button>
			{:else if userDetail}
				{@const hasFaltas = userDetail.faltas > 0}
				{@const isOpen = expanded.has(userDetail.user_id)}
				{@const detailUserId = userDetail.user_id}
				<GlassPanel padding="1.5rem" class={'audit-card' + (hasFaltas ? ' danger' : '')}>
					<div class="audit-header">
						<div class="audit-identity">
							<span class="audit-email">{userDetail.user_email}</span>
							<span class="audit-name">{userDetail.user_name}</span>
						</div>
						<ComplianceGauge
							reported={userDetail.reported_days}
							expected={userDetail.expected_days}
							size={100}
							strokeWidth={8}
						/>
					</div>
					<div class="audit-detail-stats">
						<span class="stat">
							Reportados: <strong>{userDetail.reported_days}</strong> / {userDetail.expected_days}
						</span>
						<span class="stat faltas faltas-{hasFaltas ? 'on' : 'off'}">
							Faltas: <strong>{userDetail.faltas}</strong>
						</span>
						{#if hasFaltas}
							<button
								type="button"
								class="faltas-toggle"
								onclick={() => toggleFaltas(detailUserId)}
								aria-expanded={isOpen}
							>
								{isOpen ? 'Ocultar fechas' : 'Ver fechas'}
							</button>
						{/if}
					</div>

					{#if hasFaltas}
						<div class="faltas-body" class:expanded={isOpen}>
							<div class="faltas-inner">
								<ul class="faltas-grid">
									{#each userDetail.falta_dates as date (date)}
										<li class="falta-chip">{formatDate(date)}</li>
									{/each}
								</ul>
							</div>
						</div>
					{/if}
				</GlassPanel>
			{/if}
		{:else}
			<!-- All-users view (existing behavior) -->
			{#if loading}
				<LoadingSpinner />
			{:else if error}
				<p class="msg error">{error}</p>
				<Button variant="secondary" onclick={loadAudit}>Reintentar</Button>
			{:else if rows.length === 0}
				<p class="empty">Sin datos para el mes seleccionado.</p>
			{:else}
				{#each rows as row (row.user_id)}
					{@const hasFaltas = row.faltas > 0}
					{@const isOpen = expanded.has(row.user_id)}
					<GlassPanel padding="1.5rem" class={'audit-card' + (hasFaltas ? ' danger' : '')}>
						<div class="audit-header">
							<div class="audit-identity">
								<span class="audit-email">{row.user_email}</span>
								<span class="audit-stats">
									<span class="stat">
										Reportados: <strong>{row.reported_days}</strong> / {row.expected_days}
									</span>
									<span class="stat faltas faltas-{hasFaltas ? 'on' : 'off'}">
										Faltas: <strong>{row.faltas}</strong>
									</span>
								</span>
							</div>
							{#if hasFaltas}
								<button
									type="button"
									class="faltas-toggle"
									onclick={() => toggleFaltas(row.user_id)}
									aria-expanded={isOpen}
								>
									{isOpen ? 'Ocultar fechas' : 'Ver fechas'}
								</button>
							{/if}
						</div>

						{#if hasFaltas}
							<div class="faltas-body" class:expanded={isOpen}>
								<div class="faltas-inner">
									<ul class="faltas-grid">
										{#each row.falta_dates as date (date)}
											<li class="falta-chip">{formatDate(date)}</li>
										{/each}
									</ul>
								</div>
							</div>
						{/if}
					</GlassPanel>
				{/each}
			{/if}
		{/if}
	{/if}
</div>

<style>
	.audit-page {
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

	.controls-bar {
		display: flex;
		align-items: center;
		gap: 1rem;
		flex-wrap: wrap;
	}

	.control-group {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}

	.control-group label {
		font-family: var(--font-heading);
		font-size: 0.85rem;
		font-weight: 700;
		color: var(--text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.1em;
	}

	.control-group input,
	.control-group select {
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

	.control-group input:focus,
	.control-group select:focus {
		border-color: var(--neon-cyan);
	}

	.control-group select {
		cursor: pointer;
		max-width: 280px;
	}

	.audit-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 1rem;
		flex-wrap: wrap;
	}

	.audit-identity {
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
	}

	.audit-email {
		font-family: var(--font-body);
		font-size: 1rem;
		font-weight: 600;
		color: var(--text-primary);
	}

	.audit-name {
		font-family: var(--font-body);
		font-size: 0.85rem;
		color: var(--text-secondary);
	}

	.audit-detail-stats {
		display: flex;
		gap: 1rem;
		flex-wrap: wrap;
		align-items: center;
		font-family: var(--font-body);
		font-size: 0.85rem;
		color: var(--text-secondary);
		margin-top: 0.75rem;
	}

	.audit-stats {
		display: flex;
		gap: 1rem;
		flex-wrap: wrap;
		font-family: var(--font-body);
		font-size: 0.85rem;
		color: var(--text-secondary);
	}

	.stat strong {
		color: var(--text-primary);
	}

	.faltas-on {
		color: var(--neon-pink);
	}

	.faltas-on strong {
		color: var(--neon-pink);
	}

	.faltas-off {
		color: var(--neon-green);
	}

	.faltas-off strong {
		color: var(--neon-green);
	}

	.faltas-toggle {
		background: none;
		border: 1px solid var(--glass-border);
		border-radius: 6px;
		padding: 0.3rem 0.7rem;
		cursor: pointer;
		font-family: var(--font-body);
		font-size: 0.78rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--neon-cyan);
		transition:
			border-color var(--transition-speed) ease,
			background var(--transition-speed) ease;
	}

	.faltas-toggle:hover {
		border-color: var(--neon-cyan);
		background: rgba(0, 255, 255, 0.08);
	}

	/* Collapsible falta_dates — grid-template-rows trick like TaskCard. */
	.faltas-body {
		display: grid;
		grid-template-rows: 0fr;
		transition: grid-template-rows 0.3s ease;
	}

	.faltas-body.expanded {
		grid-template-rows: 1fr;
	}

	.faltas-inner {
		overflow: hidden;
		padding-top: 0;
	}

	.faltas-body.expanded .faltas-inner {
		padding-top: 0.75rem;
	}

	.faltas-grid {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
	}

	.falta-chip {
		font-family: var(--font-body);
		font-size: 0.8rem;
		font-weight: 600;
		color: var(--neon-pink);
		background: rgba(255, 0, 255, 0.1);
		border: 1px solid rgba(255, 0, 255, 0.3);
		border-radius: 6px;
		padding: 0.2rem 0.55rem;
	}

	:global(.audit-card.danger) {
		border-color: rgba(255, 0, 255, 0.35);
	}

	.empty {
		font-family: var(--font-body);
		font-size: 0.9rem;
		color: var(--text-secondary);
		opacity: 0.7;
	}

	.msg {
		font-family: var(--font-body);
		font-size: 0.9rem;
		font-weight: 600;
		padding: 0.5rem 0.75rem;
		border-radius: 8px;
		border: 1px solid var(--glass-border);
	}

	.msg.error {
		color: var(--neon-pink);
		background: rgba(255, 0, 255, 0.08);
		border-color: rgba(255, 0, 0, 0.3);
	}

	@media (max-width: 900px) {
		.audit-page {
			padding-top: 5rem;
		}
	}
</style>
