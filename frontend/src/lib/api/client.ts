export class ApiError extends Error {
	status: number;

	constructor(status: number, message: string) {
		super(message);
		this.status = status;
	}
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
	const response = await fetch(path, {
		...options,
		credentials: 'include',
		headers: {
			'Content-Type': 'application/json',
			...options.headers
		}
	});

	if (response.status === 401) {
		throw new ApiError(401, 'Unauthorized');
	}

	if (!response.ok) {
		throw new ApiError(response.status, await response.text());
	}

	return response.json();
}
