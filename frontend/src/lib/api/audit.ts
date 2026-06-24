import { api } from './client';

export interface AuditUser {
	id: string;
	email: string;
	name: string;
	is_admin: boolean;
	is_audited: boolean;
	is_seed: boolean;
}

export interface UserMonthAudit {
	user_id: string;
	user_email: string;
	expected_days: number;
	reported_days: number;
	faltas: number;
	falta_dates: string[];
}

export interface AllowedEmail {
	email: string;
	added_by: string | null;
	created_at: string;
	is_seed: boolean;
}

export async function getAuditUsers(): Promise<AuditUser[]> {
	return api<AuditUser[]>('/api/audit/users');
}

export async function updateUserFlags(
	id: string,
	flags: { is_admin?: boolean; is_audited?: boolean }
): Promise<AuditUser> {
	return api<AuditUser>(`/api/audit/users/${id}`, {
		method: 'PATCH',
		body: JSON.stringify(flags)
	});
}

export async function getMonthlyAudit(year: number, month: number): Promise<UserMonthAudit[]> {
	return api<UserMonthAudit[]>(
		`/api/audit/monthly?year=${year}&month=${month}`
	);
}

export async function runReminders(): Promise<{ status: string }> {
	return api<{ status: string }>('/api/audit/run-reminders', { method: 'POST' });
}

export async function getAllowedEmails(): Promise<AllowedEmail[]> {
	return api<AllowedEmail[]>('/api/audit/allowed-emails');
}

export async function addAllowedEmail(email: string): Promise<AllowedEmail> {
	return api<AllowedEmail>('/api/audit/allowed-emails', {
		method: 'POST',
		body: JSON.stringify({ email })
	});
}

export async function removeAllowedEmail(email: string): Promise<void> {
	await api(`/api/audit/allowed-emails/${encodeURIComponent(email)}`, {
		method: 'DELETE'
	});
}
