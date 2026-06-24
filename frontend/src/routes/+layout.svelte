<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { checkAuth, getAuthState, logout } from '$lib/stores/auth.svelte';
	import Header from '$lib/components/Header.svelte';
	import favicon from '$lib/assets/favicon.svg';

	let { children } = $props();
	const auth = getAuthState();

	const publicRoutes = ['/login', '/register', '/no-access'];

	onMount(() => {
		checkAuth();
	});

	$effect(() => {
		if (auth.authLoaded && !auth.isAuthenticated) {
			const currentPath = page.url.pathname;
			if (!publicRoutes.includes(currentPath)) {
				window.location.href = '/login';
			}
		}
	});
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

{#if !auth.authLoaded}
	<div class="loading-screen">
		<p>Cargando...</p>
	</div>
{:else}
	{#if auth.isAuthenticated}
		<Header user={auth.user} onlogout={logout} />
	{/if}
	{@render children()}
{/if}

<style>
	.loading-screen {
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 100vh;
		color: #999;
	}
</style>
