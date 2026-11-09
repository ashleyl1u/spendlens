import { NavLink, Outlet } from "react-router-dom";

import { useAuth } from "../auth/useAuth";

export function Layout() {
  const { user, logout } = useAuth();
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
