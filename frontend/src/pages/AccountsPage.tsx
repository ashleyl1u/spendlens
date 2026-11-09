import { useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";

import { EmptyState, ErrorMessage, Loading } from "../components/Status";
import { api } from "../lib/api";
import type { Account } from "../lib/types";
import { useAsync } from "../lib/useAsync";

export function AccountsPage() {
  const accounts = useAsync((signal) => api<Account[]>("/accounts", { signal }), []);

  return (
    <>
      <h1>Accounts</h1>
      <p className="lede">The cards you upload statements for.</p>
      <div className="two-column">
        <section aria-labelledby="your-accounts" className="card">
          <h2 id="your-accounts">Your accounts</h2>
          {accounts.status === "loading" && <Loading label="Loading accounts…" />}
          {accounts.status === "error" && (
            <ErrorMessage error={accounts.error} onRetry={accounts.reload} />
          )}
          {accounts.status === "success" &&
            (accounts.data.length === 0 ? (
              <EmptyState title="No accounts yet">
                <p>Add your first card with the form, then upload a statement for it.</p>
              </EmptyState>
            ) : (
              <ul className="account-list">
                {accounts.data.map((account) => (
                  <li key={account.id} className="account-item">
                    <span className="account-name">{account.nickname}</span>
                    <span className="account-meta">
                      {account.bank}
                      {account.last4 ? ` · ending in ${account.last4}` : ""} · {account.currency}
                    </span>
                  </li>
                ))}
              </ul>
            ))}
          {accounts.status === "success" && accounts.data.length > 0 && (
            <p>
              <Link to="/upload">Upload a statement</Link>
            </p>
          )}
        </section>
        <section aria-labelledby="add-account" className="card">
          <h2 id="add-account">Add an account</h2>
          <AccountForm onCreated={accounts.reload} />
        </section>
      </div>
    </>
  );
}

function AccountForm({ onCreated }: { onCreated: () => void }) {
  const [bank, setBank] = useState("RBC");
  const [nickname, setNickname] = useState("");
  const [last4, setLast4] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSaved(null);
    if (!nickname.trim()) return setError("Give the account a nickname, such as “RBC Visa”.");
    if (last4 && !/^\d{4}$/.test(last4)) {
      return setError("Last 4 digits must be exactly four numbers, or left blank.");
    }
    setBusy(true);
    try {
      const account = await api<Account>("/accounts", {
        body: { bank: bank.trim() || "RBC", nickname: nickname.trim(), last4: last4 || null },
      });
      setSaved(`Added ${account.nickname}.`);
      setNickname("");
      setLast4("");
      onCreated();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate>
      <div className="field">
        <label htmlFor="bank">Bank</label>
        <input id="bank" value={bank} maxLength={50} onChange={(e) => setBank(e.target.value)} />
        <p className="hint">Only RBC credit card statements can be uploaded for now.</p>
      </div>
      <div className="field">
        <label htmlFor="nickname">Nickname</label>
        <input
          id="nickname"
          required
          maxLength={100}
          placeholder="RBC Visa"
          value={nickname}
          onChange={(e) => setNickname(e.target.value)}
        />
      </div>
      <div className="field">
        <label htmlFor="last4">Last 4 digits (optional)</label>
        <input
          id="last4"
          inputMode="numeric"
          autoComplete="off"
          pattern="\d{4}"
          value={last4}
          // Keep only digits, then the first four, so a full card number can never be
          // entered. No maxLength: it would cut a paste like "ab12 34" before the digits
          // are picked out of it.
          onChange={(e) => setLast4(e.target.value.replace(/\D/g, "").slice(0, 4))}
          aria-describedby="last4-hint"
        />
        <p id="last4-hint" className="hint">
          Never your full card number. Only the last four digits are stored.
        </p>
      </div>
      {error && (
        <p className="status status-error" role="alert">
          {error}
        </p>
      )}
      {saved && (
        <p className="status status-success" role="status">
          {saved}
        </p>
      )}
      <button type="submit" className="button button-primary" disabled={busy}>
        {busy ? "Adding…" : "Add account"}
      </button>
    </form>
  );
}
