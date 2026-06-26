import { api } from './client';

export interface TelegramStatus {
	linked: boolean;
	chat_id: string | null;
}

export interface TelegramLinkResponse {
	code: string;
	bot_username: string;
	expires_in: number;
}

export async function getTelegramStatus(): Promise<TelegramStatus> {
	return api<TelegramStatus>('/api/telegram/status');
}

export async function linkTelegram(): Promise<TelegramLinkResponse> {
	return api<TelegramLinkResponse>('/api/telegram/link', { method: 'POST' });
}

export async function unlinkTelegram(): Promise<{ status: string }> {
	return api<{ status: string }>('/api/telegram/link', { method: 'DELETE' });
}
