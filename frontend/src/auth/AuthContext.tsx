import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

import { api, ApiError } from "../lib/api";
import { tokenStore } from "../lib/tokenStore";
import type { User } from "../lib/types";
import { AuthContext } from "./useAuth";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState(() => tokenStore.get());
  const [user, setUser] = useState<User | null>(null);
  const [sessionEnded, setSessionEnded] = useState(false);
  const loggingOut = useRef(false);

  // Every token change (login, logout, or a 401 anywhere) flows through the store.
  useEffect(
    () =>
      tokenStore.subscribe((next) => {
        if (next === null && !loggingOut.current) setSessionEnded(true);
        loggingOut.current = false;
        setToken(next);
        if (next === null) setUser(null);
      }),
    [],
  );

  useEffect(() => {
    if (!token) return;
    const controller = new AbortController();
    api<User>("/auth/me", { signal: controller.signal })
      .then(setUser)
      .catch(() => undefined); // a 401 here already signed the user out
    return () => controller.abort();
  }, [token]);

  const login = useCallback(async (email: string, password: string) => {
    // OAuth2 password flow: a form body with the email as "username".
    const form = new URLSearchParams({ username: email.trim(), password });
    try {
      const result = await api<{ access_token: string }>("/auth/login", { body: form });
      setSessionEnded(false);
      tokenStore.set(result.access_token);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        throw new ApiError(401, "That email and password don't match an account.");
      }
      throw error;
    }
  }, []);

  const register = useCallback(
    async (email: string, password: string) => {
      try {
        await api<User>("/auth/register", { body: { email: email.trim(), password } });
      } catch (error) {
        if (error instanceof ApiError && error.status === 409) {
          throw new ApiError(409, "An account with this email already exists. Log in instead.");
        }
        throw error;
      }
      await login(email, password);
    },
    [login],
  );

  const logout = useCallback(() => {
    loggingOut.current = true;
    setSessionEnded(false);
    tokenStore.clear();
  }, []);

  const value = useMemo(
    () => ({ token, user, sessionEnded, login, register, logout }),
    [token, user, sessionEnded, login, register, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
