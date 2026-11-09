import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/useAuth";

const MIN_PASSWORD = 8; // matches UserCreate in the backend

export function AuthPage({ mode }: { mode: "login" | "register" }) {
  const { login, register, sessionEnded } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const isLogin = mode === "login";
  const title = isLogin ? "Log in" : "Create an account";

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (!isLogin && password.length < MIN_PASSWORD) {
      setError(`Use a password of at least ${MIN_PASSWORD} characters.`);
      return;
    }
    setBusy(true);
    try {
      await (isLogin ? login(email, password) : register(email, password));
      const from = (location.state as { from?: string } | null)?.from;
      navigate(from && from !== "/login" ? from : "/", { replace: true });
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <main id="main" className="auth-page">
      <div className="card auth-card">
        <p className="brand">spendlens</p>
        <h1>{title}</h1>
        {isLogin && sessionEnded && !error && (
          <p className="status status-info" role="status">
            Your session has ended. Please log in again.
          </p>
        )}
        <form onSubmit={submit} noValidate>
          <div className="field">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              aria-invalid={Boolean(error) || undefined}
              aria-describedby={error ? "auth-error" : undefined}
            />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              autoComplete={isLogin ? "current-password" : "new-password"}
              required
              minLength={isLogin ? undefined : MIN_PASSWORD}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-invalid={Boolean(error) || undefined}
              aria-describedby={[error ? "auth-error" : "", isLogin ? "" : "password-hint"]
                .filter(Boolean)
                .join(" ") || undefined}
            />
            {!isLogin && (
              <p id="password-hint" className="hint">
                At least {MIN_PASSWORD} characters.
              </p>
            )}
          </div>
          {error && (
            <p id="auth-error" className="status status-error" role="alert">
              {error}
            </p>
          )}
          <button type="submit" className="button button-primary button-block" disabled={busy}>
            {busy ? (isLogin ? "Logging in…" : "Creating account…") : title}
          </button>
        </form>
        <p className="auth-switch">
          {isLogin ? (
            <>
              New to spendlens? <Link to="/register">Create an account</Link>
            </>
          ) : (
            <>
              Already have an account? <Link to="/login">Log in</Link>
            </>
          )}
        </p>
      </div>
    </main>
  );
}
