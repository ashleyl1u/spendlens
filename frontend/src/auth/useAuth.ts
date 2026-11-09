import { createContext, useContext } from "react";

import type { User } from "../lib/types";

export interface AuthState {
  token: string | null;
  user: User | null;
  /** Set when the server ended the session (a 401), so the login page can say why. */
  sessionEnded: boolean;
  login(email: string, password: string): Promise<void>;
  register(email: string, password: string): Promise<void>;
  logout(): void;
}

export const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}
