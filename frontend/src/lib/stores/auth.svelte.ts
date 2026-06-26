import { getMe, getGoogleLoginUrl, logout as apiLogout } from '$lib/api/auth';
import type { UserInfo } from '$lib/api/auth';

let user = $state<UserInfo | null>(null);
let isAuthenticated = $state(false);
let authLoaded = $state(false);

export function getAuthState() {
	return {
		get user() {
			return user;
		},
		get isAuthenticated() {
			return isAuthenticated;
		},
		get authLoaded() {
			return authLoaded;
		},
		get isAdmin() {
			return user?.is_admin ?? false;
		},
		get isAudited() {
			return user?.is_audited ?? false;
		}
	};
}

export async function checkAuth(): Promise<void> {
	try {
		const me = await getMe();
		user = me;
		isAuthenticated = true;
	} catch {
		user = null;
		isAuthenticated = false;
	} finally {
		authLoaded = true;
	}
}

export function login(): void {
	window.location.href = getGoogleLoginUrl();
}

export async function logout(): Promise<void> {
	try {
		await apiLogout();
	} finally {
		user = null;
		isAuthenticated = false;
		authLoaded = true;
		window.location.href = '/login';
	}
}
