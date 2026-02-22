/**
 * Centralized API client — single source of truth for the backend base URL
 * and typed fetch helpers used across all frontend components.
 */

export const API_BASE: string =
  (import.meta as unknown as { env?: { VITE_API_URL?: string } }).env
    ?.VITE_API_URL ?? 'http://localhost:8000';

const DEFAULT_TIMEOUT_MS = 30_000;

/**
 * Build an AbortSignal that fires after `timeoutMs` milliseconds.
 * If the caller already supplied a signal, combine it with the timeout so
 * that *either* source can abort the request.
 */
function withTimeout(
  timeoutMs: number,
  callerSignal?: AbortSignal | null,
): { signal: AbortSignal; cleanup: () => void } {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  const cleanup = () => clearTimeout(timer);

  if (callerSignal) {
    // If the caller's signal already fired, abort immediately.
    if (callerSignal.aborted) {
      clearTimeout(timer);
      controller.abort(callerSignal.reason);
    } else {
      const onCallerAbort = () => {
        clearTimeout(timer);
        controller.abort(callerSignal.reason);
      };
      callerSignal.addEventListener('abort', onCallerAbort, { once: true });
    }
  }

  return { signal: controller.signal, cleanup };
}

/** Wrap AbortError into a friendlier timeout message. */
function rethrowTimeout(err: unknown): never {
  if (err instanceof DOMException && err.name === 'AbortError') {
    throw new Error('Request timed out. Please check your connection and try again.');
  }
  throw err;
}

export interface FetchOptions extends RequestInit {
  /** Per-request timeout in milliseconds (default: 30 000). */
  timeoutMs?: number;
}

/** GET JSON from the backend. Returns parsed response or throws. */
export async function fetchJSON<T>(path: string, options?: FetchOptions): Promise<T> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, signal: callerSignal, ...rest } = options ?? {};
  const { signal, cleanup } = withTimeout(timeoutMs, callerSignal);
  try {
    const res = await fetch(`${API_BASE}${path}`, { ...rest, signal });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw Object.assign(new Error((body as { detail?: string }).detail ?? res.statusText), {
        status: res.status,
        body,
      });
    }
    return res.json() as Promise<T>;
  } catch (err) {
    return rethrowTimeout(err);
  } finally {
    cleanup();
  }
}

/** POST JSON to the backend. Returns parsed response or throws. */
export async function postJSON<T>(
  path: string,
  body: unknown,
  options?: FetchOptions,
): Promise<T> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, signal: callerSignal, ...rest } = options ?? {};
  const { signal, cleanup } = withTimeout(timeoutMs, callerSignal);
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...rest.headers },
      body: JSON.stringify(body),
      ...rest,
      signal,
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
  } catch (err) {
    return rethrowTimeout(err);
  } finally {
    cleanup();
  }
}
