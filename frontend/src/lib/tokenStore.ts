/**
 * Holds the login token: in memory for speed, and in localStorage so a page refresh keeps
 * you signed in. Storage can be missing or throw (private windows, blocked site data), so
 * every access is guarded and the in-memory copy keeps working on its own.
 *
 * The token is the only credential the frontend ever holds; there are no API keys here.
 */

export const STORAGE_KEY = "spendlens.token";

type Listener = (token: string | null) => void;

export interface TokenStore {
  get(): string | null;
  set(token: string): void;
  clear(): void;
  subscribe(listener: Listener): () => void;
}

export function createTokenStore(
  storage: Storage | null = safeLocalStorage(),
  now: () => number = Date.now,
): TokenStore {
  let token: string | null = read(storage);
  if (token && isExpired(token, now())) {
    token = null;
    write(storage, null);
  }
  const listeners = new Set<Listener>();
  const notify = () => listeners.forEach((listener) => listener(token));

  return {
    get() {
      // An expired token is as good as none; drop it rather than send it.
      if (token && isExpired(token, now())) {
        token = null;
        write(storage, null);
        notify();
      }
      return token;
    },
    set(next) {
      token = next;
      write(storage, next);
      notify();
    },
    clear() {
      if (token === null) return;
      token = null;
      write(storage, null);
      notify();
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

/**
 * True if the JWT's `exp` claim is in the past. A token we can't read is treated as not
 * expired: the server is the judge, and a 401 from it logs the user out anyway.
 */
export function isExpired(token: string, nowMs: number): boolean {
  const exp = readExpiry(token);
  return exp !== null && exp * 1000 <= nowMs;
}

function readExpiry(token: string): number | null {
  try {
    const payload = token.split(".")[1];
    if (!payload) return null;
    const base64 = payload.replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64 + "=".repeat((4 - (base64.length % 4)) % 4);
    const exp = JSON.parse(atob(padded)).exp;
    return typeof exp === "number" ? exp : null;
  } catch {
    return null;
  }
}

function safeLocalStorage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

function read(storage: Storage | null): string | null {
  try {
    return storage?.getItem(STORAGE_KEY) || null;
  } catch {
    return null;
  }
}

function write(storage: Storage | null, token: string | null): void {
  try {
    if (token === null) storage?.removeItem(STORAGE_KEY);
    else storage?.setItem(STORAGE_KEY, token);
  } catch {
    // Storage unavailable: the in-memory token still works until the tab closes.
  }
}

/** The app's single token store. */
export const tokenStore = createTokenStore();
