import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";

import { EmptyState, ErrorMessage, Loading } from "../components/Status";
import { api } from "../lib/api";
import type { Account, UploadResult } from "../lib/types";
import { describeUpload } from "../lib/uploadSummary";
import { useAsync } from "../lib/useAsync";

const MAX_BYTES = 2 * 1024 * 1024; // the backend's limit

export function UploadPage() {
  const accounts = useAsync((signal) => api<Account[]>("/accounts", { signal }), []);
  const [accountId, setAccountId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ data: UploadResult; filename: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (accounts.status === "success" && accounts.data.length > 0 && !accountId) {
      setAccountId(String(accounts.data[0].id));
    }
  }, [accounts, accountId]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setResult(null);
    if (!accountId) return setError("Choose the account this statement belongs to.");
    if (!file) return setError("Choose a CSV file to upload.");
    if (file.size > MAX_BYTES) return setError("That file is larger than 2 MB.");

    const form = new FormData();
    form.append("account_id", accountId);
    form.append("file", file);
    setBusy(true);
    try {
      const data = await api<UploadResult>("/uploads", { body: form });
      setResult({ data, filename: file.name });
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (accounts.status === "loading") return <Loading label="Loading accounts…" />;
  if (accounts.status === "error") {
    return <ErrorMessage error={accounts.error} onRetry={accounts.reload} />;
  }

  return (
    <>
      <h1>Upload a statement</h1>
      <p className="lede">Upload the CSV export from RBC online banking.</p>
      {accounts.data.length === 0 ? (
        <EmptyState title="Add an account first">
          <p>
            Statements are uploaded into an account. <Link to="/accounts">Add an account</Link>,
            then come back here.
          </p>
        </EmptyState>
      ) : (
        <section className="card narrow" aria-labelledby="upload-heading">
          <h2 id="upload-heading" className="visually-hidden">
            Upload form
          </h2>
          <form onSubmit={submit} noValidate>
            <div className="field">
              <label htmlFor="account">Account</label>
              <select id="account" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
                {accounts.data.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.nickname}
                    {account.last4 ? ` (…${account.last4})` : ""}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="file">CSV file</label>
              <input
                id="file"
                ref={fileInput}
                type="file"
                accept=".csv,text/csv"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                aria-describedby="file-hint"
              />
              <p id="file-hint" className="hint">
                Up to 2 MB. Uploading the same file again is safe: rows already saved are skipped.
              </p>
            </div>
            {error && (
              <p className="status status-error" role="alert">
                {error}
              </p>
            )}
            <button type="submit" className="button button-primary" disabled={busy}>
              {busy ? "Uploading and categorizing…" : "Upload"}
            </button>
          </form>
        </section>
      )}
      {result && <UploadSummary result={result.data} filename={result.filename} />}
    </>
  );
}

function UploadSummary({ result, filename }: { result: UploadResult; filename: string }) {
  return (
    <section className="card narrow result" role="status" aria-labelledby="result-heading">
      <h2 id="result-heading">Uploaded {filename}</h2>
      {describeUpload(result).map((line) => (
        <p key={line}>{line}</p>
      ))}
      <p>
        <Link to="/">See your dashboard</Link>
      </p>
    </section>
  );
}
