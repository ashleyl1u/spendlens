import { describe, expect, it, vi } from "vitest";

import { createApi } from "./api";
import { STORAGE_KEY, createTokenStore, isExpired } from "./tokenStore";

const NOW = Date.UTC(2026, 10, 9, 12, 0, 0);

/** A JWT-shaped token (unsigned) with the given exp, in seconds. */
function jwt(exp: number | undefined): string {
  const encode = (value: object) =>
    btoa(JSON.stringify(value)).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
  return `${encode({ alg: "HS256" })}.${encode(exp === undefined ? { sub: "1" } : { sub: "1", exp })}.sig`;
}

const valid = jwt(NOW / 1000 + 3600);
const expired = jwt(NOW / 1000 - 1);

function memoryStorage(initial: Record<string, string> = {}): Storage {
  const data = new Map(Object.entries(initial));
  return {
    get length() {
      return data.size;
    },
    clear: () => data.clear(),
    getItem: (key) => data.get(key) ?? null,
    key: (i) => [...data.keys()][i] ?? null,
    removeItem: (key) => void data.delete(key),
    setItem: (key, value) => void data.set(key, value),
  };
}

const brokenStorage: Storage = {
  length: 0,
  clear() {},
  key: () => null,
  getItem() {
    throw new Error("SecurityError");
  },
  setItem() {
    throw new Error("QuotaExceededError");
  },
  removeItem() {
    throw new Error("SecurityError");
  },
};

describe("token store", () => {
  it("keeps the token in memory and in localStorage", () => {
    const storage = memoryStorage();
    const store = createTokenStore(storage, () => NOW);

    store.set(valid);

    expect(store.get()).toBe(valid);
    expect(storage.getItem(STORAGE_KEY)).toBe(valid);
  });

  it("restores the token after a refresh", () => {
    const storage = memoryStorage({ [STORAGE_KEY]: valid });
    expect(createTokenStore(storage, () => NOW).get()).toBe(valid);
  });

  it("starts signed out when nothing is stored", () => {
    expect(createTokenStore(memoryStorage(), () => NOW).get()).toBeNull();
  });

  it("clear removes the token from memory and storage", () => {
    const storage = memoryStorage({ [STORAGE_KEY]: valid });
    const store = createTokenStore(storage, () => NOW);

    store.clear();

    expect(store.get()).toBeNull();
    expect(storage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("drops a stored token that has already expired", () => {
    const storage = memoryStorage({ [STORAGE_KEY]: expired });
    expect(createTokenStore(storage, () => NOW).get()).toBeNull();
    expect(storage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("drops a token that expires while the app is open, and tells listeners", () => {
    let now = NOW;
    const store = createTokenStore(memoryStorage(), () => now);
    const listener = vi.fn();
    store.set(jwt(NOW / 1000 + 60));
    store.subscribe(listener);

    now = NOW + 61_000;

    expect(store.get()).toBeNull();
    expect(listener).toHaveBeenCalledWith(null);
  });

  it("notifies subscribers on login and logout, and stops after unsubscribe", () => {
    const store = createTokenStore(memoryStorage(), () => NOW);
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);

    store.set(valid);
    store.clear();
    store.clear(); // already signed out: no second notification
    unsubscribe();
    store.set(valid);

    expect(listener.mock.calls).toEqual([[valid], [null]]);
  });

  it("still works in memory when storage is unavailable", () => {
    const store = createTokenStore(brokenStorage, () => NOW);
    expect(store.get()).toBeNull();

    store.set(valid);
    expect(store.get()).toBe(valid);
    store.clear();
    expect(store.get()).toBeNull();
  });

  it("works with no storage at all", () => {
    const store = createTokenStore(null, () => NOW);
    store.set(valid);
    expect(store.get()).toBe(valid);
  });
});

describe("isExpired", () => {
  it("reads exp from the token", () => {
    expect(isExpired(valid, NOW)).toBe(false);
    expect(isExpired(expired, NOW)).toBe(true);
  });

  it("leaves tokens it can't read to the server", () => {
    expect(isExpired("not-a-jwt", NOW)).toBe(false);
    expect(isExpired("a.%%%.c", NOW)).toBe(false);
    expect(isExpired(jwt(undefined), NOW)).toBe(false);
  });
});

describe("api client and the token", () => {
  function respond(status: number, body: unknown = {}) {
    return vi.fn(async () => new Response(JSON.stringify(body), { status }));
  }

  it("sends the token as a bearer header", async () => {
    const store = createTokenStore(memoryStorage(), () => NOW);
    store.set(valid);
    const fetchMock = respond(200, []);

    await createApi(store, fetchMock)("/accounts");

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect((init.headers as Record<string, string>).Authorization).toBe(`Bearer ${valid}`);
  });

  it("signs the user out on any 401", async () => {
    const storage = memoryStorage();
    const store = createTokenStore(storage, () => NOW);
    store.set(valid);
    const listener = vi.fn();
    store.subscribe(listener);

    const request = createApi(store, respond(401, { detail: "Could not validate credentials" }));

    await expect(request("/dashboard/summary")).rejects.toMatchObject({ status: 401 });
    expect(store.get()).toBeNull();
    expect(storage.getItem(STORAGE_KEY)).toBeNull();
    expect(listener).toHaveBeenCalledWith(null);
  });

  it("keeps the token on other errors", async () => {
    const store = createTokenStore(memoryStorage(), () => NOW);
    store.set(valid);

    const request = createApi(store, respond(404, { detail: "Account not found" }));

    await expect(request("/uploads", { body: new FormData() })).rejects.toThrow("Account not found");
    expect(store.get()).toBe(valid);
  });

  it("a failed login (401 with no token) shows the server's message", async () => {
    const store = createTokenStore(memoryStorage(), () => NOW);
    const request = createApi(store, respond(401, { detail: "Incorrect email or password" }));

    await expect(request("/auth/login", { body: new URLSearchParams() })).rejects.toThrow(
      "Incorrect email or password",
    );
  });

  it("turns validation errors into readable text", async () => {
    const store = createTokenStore(memoryStorage(), () => NOW);
    const request = createApi(
      store,
      respond(422, {
        detail: [{ loc: ["body", "last4"], msg: "String should match pattern '^\\d{4}$'" }],
      }),
    );
    await expect(request("/accounts", { body: { nickname: "x" } })).rejects.toThrow(
      /^Last 4 digits: String should match/,
    );
  });
});
