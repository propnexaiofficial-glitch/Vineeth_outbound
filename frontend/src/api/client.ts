const API_KEY_STORAGE_KEY = 'voice_agent_api_key';

export function getApiKey(): string {
  return localStorage.getItem(API_KEY_STORAGE_KEY) || '';
}

export function setApiKey(key: string): void {
  localStorage.setItem(API_KEY_STORAGE_KEY, key);
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const apiKey = getApiKey();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };
  if (apiKey) {
    headers['X-API-Key'] = apiKey;
  }

  const response = await fetch(path, { ...options, headers });

  if (response.status === 401) {
    throw new ApiError(401, 'Unauthorized: Invalid or missing API key');
  }
  if (response.status === 429) {
    const retryAfter = response.headers.get('Retry-After') || '60';
    throw new ApiError(429, `Rate limit exceeded. Retry after ${retryAfter}s`);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(response.status, (body as { detail?: string }).detail || response.statusText);
  }

  return response.json();
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: JSON.stringify(body) }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PUT', body: JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
};
