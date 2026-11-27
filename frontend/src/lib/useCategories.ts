import { api } from "./api";
import { useAsync } from "./useAsync";

// The list is the same for everyone and never changes while the app runs, so it is
// fetched once and shared. A failed fetch is not cached, so a retry can succeed.
let cached: Promise<string[]> | null = null;

function loadCategories(): Promise<string[]> {
  cached ??= api<string[]>("/categories").catch((error) => {
    cached = null;
    throw error;
  });
  return cached;
}

/** The backend's fixed category list, from GET /categories. */
export function useCategories() {
  return useAsync(() => loadCategories(), []);
}
