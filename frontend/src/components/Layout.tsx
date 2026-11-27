import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "../auth/useAuth";
import { api } from "../lib/api";
import { onTransactionsChanged } from "../lib/events";
import type { TransactionPage } from "../lib/types";

/** How many transactions need review: refreshed on navigation and after changes. */
function useReviewCount(): number | null {
  const location = useLocation();
  const [count, setCount] = useState<number | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => onTransactionsChanged(() => setVersion((v) => v + 1)), []);

  useEffect(() => {
    const controller = new AbortController();
    api<TransactionPage>("/transactions", {
      query: { needs_review: true, limit: 1 },
      signal: controller.signal,
    })
      .then((page) => setCount(page.total))
      .catch(() => undefined); // the count is a nicety; the page itself reports errors
    return () => controller.abort();
  }, [location.pathname, version]);

  return count;
}

export function Layout() {
  const { user, logout } = useAuth();
  const reviewCount = useReviewCount();
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="site-header">
        <div className="site-header-inner">
          <span className="brand">spendlens</span>
          <nav aria-label="Main">
            <ul className="nav-list">
              <li>
                <NavLink to="/" end>
                  Dashboard
                </NavLink>
              </li>
              <li>
                <NavLink to="/transactions">
                  Transactions
                  {reviewCount !== null && reviewCount > 0 && (
                    <span className="badge">
                      {reviewCount}
                      <span className="visually-hidden"> need review</span>
                    </span>
                  )}
                </NavLink>
              </li>
              <li>
                <NavLink to="/ask">Ask</NavLink>
              </li>
              <li>
                <NavLink to="/accounts">Accounts</NavLink>
              </li>
              <li>
                <NavLink to="/upload">Upload</NavLink>
              </li>
            </ul>
          </nav>
          <div className="account-menu">
            {user && <span className="user-email">{user.email}</span>}
            <button type="button" className="button button-secondary" onClick={logout}>
              Log out
            </button>
          </div>
        </div>
      </header>
      <main id="main" className="page" tabIndex={-1}>
        <Outlet />
      </main>
    </>
  );
}
