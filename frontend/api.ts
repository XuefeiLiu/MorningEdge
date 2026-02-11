/**
 * Centralized API client — single source of truth for the backend base URL
 * and typed fetch helpers used across all frontend components.
 */

export const API_BASE: string =
  (import.meta as unknown as { env?: { VITE_API_URL?: string } }).env
    ?.VITE_API_URL ?? 'http://localhost:8000';

/** GET JSON from the backend. Returns parsed response or throws. */
export async function fetchJSON<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, options);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw Object.assign(new Error((body as { detail?: string }).detail ?? res.statusText), {
      status: res.status,
      body,
    });
  }
  return res.json() as Promise<T>;
}

/** POST JSON to the backend. Returns parsed response or throws. */
export async function postJSON<T>(
  path: string,
  body: unknown,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    body: JSON.stringify(body),
    ...options,
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    const err = Object.assign(
      new Error((data as { detail?: string }).detail ?? res.statusText),
      { status: res.status, body: data },
    );
    throw err;
  }
  return res.json() as Promise<T>;
}
