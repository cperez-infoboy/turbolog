import {
	connectJira as apiConnect,
	disconnectJira as apiDisconnect,
	getConnectionStatus
} from '$lib/api/jira';

let connected = $state(false);
let jiraEmail = $state<string | null>(null);
let displayName = $state<string | null>(null);
let loading = $state(false);
let error = $state<string | null>(null);

export function getJiraConnectionState() {
	return {
		get connected() {
			return connected;
		},
		get jiraEmail() {
			return jiraEmail;
		},
		get displayName() {
			return displayName;
		},
		get loading() {
			return loading;
		},
		get error() {
			return error;
		}
	};
}

export async function checkConnection(): Promise<void> {
	loading = true;
	error = null;
	try {
		const status = await getConnectionStatus();
		connected = true;
		jiraEmail = status.email;
		displayName = null; // not returned by current API
	} catch {
		connected = false;
		jiraEmail = null;
		displayName = null;
	} finally {
		loading = false;
	}
}

export async function connect(email: string, token: string, domain: string): Promise<void> {
	loading = true;
	error = null;
	try {
		const result = await apiConnect(email, token, domain);
		connected = true;
		jiraEmail = result.email;
		displayName = result.display_name;
	} catch (e: unknown) {
		connected = false;
		if (e instanceof Error) {
			error = e.message;
		} else {
			error = 'Failed to connect JIRA';
		}
		throw e;
	} finally {
		loading = false;
	}
}

export async function disconnect(): Promise<void> {
	loading = true;
	error = null;
	try {
		await apiDisconnect();
		connected = false;
		jiraEmail = null;
		displayName = null;
	} catch (e: unknown) {
		if (e instanceof Error) {
			error = e.message;
		} else {
			error = 'Failed to disconnect JIRA';
		}
		throw e;
	} finally {
		loading = false;
	}
}
