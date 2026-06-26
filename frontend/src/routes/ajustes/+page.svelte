<script lang="ts">
	import { onMount } from 'svelte';
	import { getAuthState } from '$lib/stores/auth.svelte';
	import { getTelegramStatus, linkTelegram, unlinkTelegram } from '$lib/api/telegram';
	import type { TelegramStatus } from '$lib/api/telegram';
	import { ApiError } from '$lib/api/client';
	import GlassPanel from '$lib/components/GlassPanel.svelte';
	import Button from '$lib/components/Button.svelte';

	const auth = getAuthState();

	// Telegram state.
	let telegram = $state<TelegramStatus>({ linked: false, chat_id: null });
	let telegramLoading = $state(false);
	let telegramCode = $state<string | null>(null);
	let telegramBotUsername = $state<string | null>(null);
	let telegramError = $state<string | null>(null);
	let telegramSuccess = $state<string | null>(null);
	let telegramCodeExpired = $state(false);
	let telegramCodeExpiresAt = $state<number>(0);
	let codeTimer: ReturnType<typeof setTimeout> | null = null;

	// Admin guard.
	$effect(() => {
		if (auth.authLoaded && !auth.isAuthenticated) {
			window.location.href = '/login';
		}
	});

	onMount(() => {
		loadTelegramStatus();
		return () => {
			if (codeTimer) clearTimeout(codeTimer);
		};
	});

	async function loadTelegramStatus() {
		try {
			telegram = await getTelegramStatus();
		} catch {
			// Non-critical.
		}
	}

	function startCodeTimer(expiresIn: number) {
		if (codeTimer) clearTimeout(codeTimer);
		telegramCodeExpired = false;
		telegramCodeExpiresAt = Date.now() + expiresIn * 1000;
		codeTimer = setTimeout(() => {
			telegramCodeExpired = true;
		}, expiresIn * 1000);
	}

	async function handleTelegramLink() {
		if (telegramLoading) return;
		telegramLoading = true;
		telegramError = null;
		telegramSuccess = null;
		telegramCodeExpired = false;
		try {
			const result = await linkTelegram();
			telegramCode = result.code;
			telegramBotUsername = result.bot_username;
			startCodeTimer(result.expires_in);
		} catch (err) {
			telegramError = err instanceof ApiError ? err.message : 'Error al generar código.';
		} finally {
			telegramLoading = false;
		}
	}

	async function handleTelegramUnlink() {
		if (telegramLoading) return;
		if (!confirm('¿Desvincular Telegram? Dejarás de recibir notificaciones.')) return;
		telegramLoading = true;
		telegramError = null;
		telegramSuccess = null;
		if (codeTimer) clearTimeout(codeTimer);
		telegramCode = null;
		telegramCodeExpired = false;
		try {
			await unlinkTelegram();
			telegram = { linked: false, chat_id: null };
			telegramSuccess = 'Telegram desvinculado.';
		} catch (err) {
			telegramError = err instanceof ApiError ? err.message : 'Error al desvincular.';
		} finally {
			telegramLoading = false;
		}
	}

	function handleVerify() {
		if (codeTimer) clearTimeout(codeTimer);
		telegramCode = null;
		telegramCodeExpired = false;
		telegramSuccess = null;
		telegramError = null;
		loadTelegramStatus();
	}

	function handleNewCode() {
		telegramCodeExpired = false;
		telegramCode = null;
		handleTelegramLink();
	}
</script>

<svelte:head>
	<title>Turbolog — Ajustes</title>
</svelte:head>

<div class="settings-page">
	<h1 class="page-title">Ajustes</h1>

	<!-- Telegram -->
	<GlassPanel padding="1.75rem">
		<div class="section-header">
			<div class="section-header-text">
				<h2 class="section-title">Notificaciones Telegram</h2>
				<p class="section-hint">
					Recibe recordatorios automáticos por Telegram cuando no cierres el día.
				</p>
			</div>
			{#if telegram.linked}
				<span class="badge connected">Conectado</span>
			{:else}
				<span class="badge disconnected">No conectado</span>
			{/if}
		</div>

		{#if telegram.linked && !telegramCode}
			<div class="linked-info">
				<p class="hint">
					Vinculado como chat <code>{telegram.chat_id}</code>. Recibirás recordatorios
					cuando no cierres tu día de trabajo.
				</p>
				<Button
					variant="danger"
					size="sm"
					onclick={handleTelegramUnlink}
					loading={telegramLoading}
					disabled={telegramLoading}
				>
					Desvincular
				</Button>
			</div>
		{:else if telegramCode && telegramBotUsername && telegramCodeExpired}
			<div class="link-flow">
				<p class="expired-msg">El código expiró. Genera uno nuevo para continuar.</p>
				<Button
					variant="cta"
					onclick={handleNewCode}
					loading={telegramLoading}
					disabled={telegramLoading}
				>
					Generar nuevo código
				</Button>
			</div>
		{:else if telegramCode && telegramBotUsername}
			<div class="link-flow">
				<p class="hint">Envía este código al bot de Telegram:</p>
				<div class="code-display">{telegramCode}</div>
				<div class="steps">
					<p class="step"><span class="step-num">1</span> Abre Telegram y busca <strong>@{telegramBotUsername}</strong></p>
					<p class="step"><span class="step-num">2</span> Inicia una conversación con el bot (presiona "Iniciar" o envía <code>/start</code>)</p>
					<p class="step"><span class="step-num">3</span> Envía el código de 6 dígitos que aparece arriba</p>
					<p class="step"><span class="step-num">4</span> El bot confirmará la vinculación. Regresa aquí y presiona "Ya vinculé, verificar"</p>
				</div>
				<div class="link-actions">
					<a
						class="bot-link"
						href="https://t.me/{telegramBotUsername}"
						target="_blank"
						rel="noopener"
					>
						Abrir @{telegramBotUsername} en Telegram →
					</a>
					<Button variant="secondary" size="sm" onclick={handleVerify}>
						Ya vinculé, verificar
					</Button>
				</div>
			</div>
		{:else}
			<div class="link-cta">
				<p class="hint">
					Vincula tu cuenta de Telegram para recibir notificaciones push. El proceso
					toma menos de un minuto.
				</p>
				<Button
					variant="cta"
					onclick={handleTelegramLink}
					loading={telegramLoading}
					disabled={telegramLoading}
				>
					Vincular Telegram
				</Button>
			</div>
		{/if}

		{#if telegramSuccess}
			<p class="msg success">{telegramSuccess}</p>
		{/if}
		{#if telegramError}
			<p class="msg error">{telegramError}</p>
		{/if}
	</GlassPanel>
</div>

<style>
	.settings-page {
		display: flex;
		flex-direction: column;
		gap: 1.5rem;
		padding: 6rem 5% 2rem;
		max-width: 700px;
		margin: 0 auto;
		min-height: 100vh;
	}

	.page-title {
		font-size: 1.6rem;
		letter-spacing: 0.05em;
	}

	.section-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 1rem;
		margin-bottom: 1rem;
	}

	.section-header-text {
		flex: 1;
	}

	.section-title {
		font-size: 1.05rem;
		margin: 0 0 0.25rem;
		letter-spacing: 0.04em;
	}

	.section-hint {
		font-family: var(--font-body);
		font-size: 0.85rem;
		color: var(--text-secondary);
		margin: 0;
		opacity: 0.85;
	}

	.badge {
		font-family: var(--font-body);
		font-size: 0.75rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		padding: 0.2rem 0.7rem;
		border-radius: 4px;
		white-space: nowrap;
		flex-shrink: 0;
	}

	.badge.connected {
		color: var(--neon-green);
		border: 1px solid var(--neon-green);
		background: rgba(0, 255, 136, 0.08);
	}

	.badge.disconnected {
		color: var(--text-secondary);
		border: 1px solid var(--glass-border);
		background: rgba(0, 0, 0, 0.3);
	}

	.hint {
		font-family: var(--font-body);
		font-size: 0.9rem;
		color: var(--text-secondary);
		margin: 0 0 1rem;
		line-height: 1.6;
	}

	.hint code {
		font-family: var(--font-heading);
		font-size: 0.85rem;
		color: var(--neon-cyan);
		background: rgba(0, 255, 255, 0.08);
		padding: 0.1rem 0.4rem;
		border-radius: 4px;
	}

	.linked-info {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}

	.link-flow {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.code-display {
		font-family: var(--font-heading);
		font-size: 2.2rem;
		font-weight: 900;
		color: var(--neon-cyan);
		text-align: center;
		letter-spacing: 0.35em;
		padding: 1rem;
		background: rgba(0, 255, 255, 0.05);
		border: 1px solid var(--glass-border);
		border-radius: 8px;
		user-select: all;
	}

	.steps {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		margin-bottom: 1rem;
	}

	.step {
		display: flex;
		align-items: flex-start;
		gap: 0.6rem;
		font-family: var(--font-body);
		font-size: 0.9rem;
		color: var(--text-secondary);
		margin: 0;
		line-height: 1.5;
	}

	.step-num {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 1.4rem;
		height: 1.4rem;
		border-radius: 50%;
		background: rgba(0, 255, 255, 0.1);
		border: 1px solid var(--glass-border);
		font-family: var(--font-heading);
		font-size: 0.7rem;
		font-weight: 700;
		color: var(--neon-cyan);
		flex-shrink: 0;
	}

	.step code {
		font-family: var(--font-heading);
		font-size: 0.85rem;
		color: var(--neon-cyan);
		background: rgba(0, 255, 255, 0.08);
		padding: 0.1rem 0.4rem;
		border-radius: 4px;
	}

	.link-actions {
		display: flex;
		align-items: center;
		gap: 1rem;
		margin-top: 0.5rem;
		flex-wrap: wrap;
	}

	.bot-link {
		font-family: var(--font-body);
		font-size: 0.95rem;
		font-weight: 600;
	}

	.link-cta {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}

	.msg {
		font-family: var(--font-body);
		font-size: 0.9rem;
		font-weight: 600;
		padding: 0.5rem 0.75rem;
		border-radius: 8px;
		border: 1px solid var(--glass-border);
		margin: 1rem 0 0;
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

	.expired-msg {
		font-family: var(--font-body);
		font-size: 0.9rem;
		color: var(--neon-pink);
		margin: 0 0 0.75rem;
	}

	@media (max-width: 900px) {
		.settings-page {
			padding-top: 5rem;
		}

		.section-header {
			flex-direction: column;
		}
	}
</style>
