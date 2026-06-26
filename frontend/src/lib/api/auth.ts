import { api } from './client';

export interface UserInfo {
	id: string;
	email: string;
	name: string;
	picture: string | null;
	created_at: string;
	is_admin: boolean;
	is_audited: boolean;
	telegram_chat_id: string | null;
}

export function getGoogleLoginUrl(): string {
	return '/api/auth/google/login';
}

export async function getMe(): Promise<UserInfo> {
	return api<UserInfo>('/api/auth/me');
}

export async function logout(): Promise<void> {
	await api('/api/auth/logout', { method: 'POST' });
}

export async function register(data: {
	google_sub: string;
	email: string;
	name: string;
	picture: string | null;
}): Promise<{ user_id: string }> {
	return api('/api/auth/register', {
		method: 'POST',
		body: JSON.stringify(data)
	});
}
