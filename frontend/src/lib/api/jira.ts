import { api } from './client';

export interface JiraConnectionStatus {
	connected: boolean;
	email: string;
	domain: string;
	last_verified: string | null;
}

export interface JiraConnectResult {
	connected: boolean;
	email: string;
	domain: string;
	display_name: string;
}

export async function connectJira(
	email: string,
	token: string,
	domain: string
): Promise<JiraConnectResult> {
	return api<JiraConnectResult>('/api/jira/connect', {
		method: 'POST',
		body: JSON.stringify({
			jira_email: email,
			api_token: token,
			jira_domain: domain
		})
	});
}

export async function disconnectJira(): Promise<void> {
	await api('/api/jira/disconnect', { method: 'DELETE' });
}

export async function getConnectionStatus(): Promise<JiraConnectionStatus> {
	return api<JiraConnectionStatus>('/api/jira/connection');
}
