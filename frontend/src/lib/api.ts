/**
 * A small fetch wrapper for the spendlens API. Requests go to relative paths (/auth,
 * /accounts, ...) and the Vite dev server proxies them to the backend.
 *
 * Any 401 on an authenticated request clears the token, which signs the user out
 * everywhere in the app (see AuthProvider).
 */

import { tokenStore, type TokenStore } from "./tokenStore";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface RequestOptions {
  method?: string;
  /** A JSON body, or FormData / URLSearchParams sent as-is. */
  body?: unknown;
  /** Search params; undefined and empty values are left out. */
  query?: Record<string, string | number | boolean | undefined | null>;
  signal?: AbortSignal;
}

export function createApi(store: TokenStore, fetchImpl: typeof fetch = (...a) => fetch(...a)) {
  async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" };
    const token = store.get();
    if (token) headers.Authorization = `Bearer ${token}`;

    let body: BodyInit | undefined;
    if (options.body instanceof FormData || options.body instanceof URLSearchParams) {
      body = options.body; // the browser sets the multipart / form content type
    } else if (options.body !== undefined) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(options.body);
    }

    let response: Response;
    try {
      response = await fetchImpl(withQuery(path, options.query), {
        method: options.method ?? (body ? "POST" : "GET"),
        headers,
        body,
        signal: options.signal,
      });
    } catch (error) {
      if ((error as Error).name === "AbortError") throw error;
      throw new ApiError(0, "Can't reach the spendlens server. Is the backend running on port 8000?");
    }

    if (response.status === 401 && token) {
      store.clear(); // the session is over; AuthProvider sends the user to login
      throw new ApiError(401, "Your session has ended. Please log in again.");
    }
    if (!response.ok) {
      throw new ApiError(response.status, await errorMessage(response));
    }
    return (response.status === 204 ? undefined : await response.json()) as T;
  }
  return request;
}

/** The app's API client. */
export const api = createApi(tokenStore);

function withQuery(path: string, query: RequestOptions["query"]): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `${path}?${text}` : path;
}

/** Turn a FastAPI error body into one readable sentence. */
export async function errorMessage(response: Response): Promise<string> {
  let detail: unknown;
  try {
    detail = (await response.json()).detail;
  } catch {
    return `The server answered ${response.status}. Please try again.`;
  }
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    // Validation errors: [{loc: ["body", "password"], msg: "..."}]
    return detail
      .map((item) => {
        const field = Array.isArray(item?.loc) ? item.loc[item.loc.length - 1] : undefined;
        const message = String(item?.msg ?? "is invalid").replace(/^Value error, /, "");
        return field && field !== "body" ? `${humanize(String(field))}: ${message}` : message;
      })
      .join(" ");
  }
  return `The server answered ${response.status}. Please try again.`;
}

function humanize(field: string): string {
  const names: Record<string, string> = { last4: "Last 4 digits", username: "Email" };
  return names[field] ?? field.charAt(0).toUpperCase() + field.slice(1).replace(/_/g, " ");
}
