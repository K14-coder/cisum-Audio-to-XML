import { Link, NavLink, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { AuthProvider, RequireAuth, useAuth } from "./auth/AuthContext";
import { APP_NAME } from "./config";
import { AdminReportsPage } from "./pages/AdminReportsPage";
import { AuthPage } from "./pages/AuthPage";
import { RightsPage, TakedownPage } from "./pages/LegalPages";
import { LibraryPage } from "./pages/LibraryPage";
import { NewSongPage } from "./pages/NewSongPage";
import { SharedPage } from "./pages/SharedPage";
import { SongPage } from "./pages/SongPage";

function Header() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  return (
    <header className="site-header">
      <Link to="/" className="brand">
        <img src="/favicon.svg" alt="" width={26} height={26} />
        <span>{APP_NAME}</span>
      </Link>
      <nav className="nav">
        {user && (
          <>
            <NavLink to="/" end>
              Songs
            </NavLink>
            <NavLink to="/new">New song</NavLink>
            {user.is_admin && !user.single_user && <NavLink to="/admin/reports">Reports</NavLink>}
          </>
        )}
      </nav>
      <div className="header-user">
        {user?.single_user ? (
          <span className="muted user-email">Running on this computer</span>
        ) : user ? (
          <>
            <span className="muted user-email" title={user.email}>
              {user.email}
            </span>
            <button
              type="button"
              className="button small"
              onClick={async () => {
                await logout();
                navigate("/login");
              }}
            >
              Log out
            </button>
          </>
        ) : user === null ? (
          <>
            <NavLink to="/login">Log in</NavLink>
            <NavLink to="/register" className="button small primary">
              Sign up
            </NavLink>
          </>
        ) : null}
      </div>
    </header>
  );
}

function Footer() {
  return (
    <footer className="site-footer">
      <nav>
        <Link to="/legal/rights">Rights notice</Link>
        <Link to="/legal/takedown">Report infringement</Link>
      </nav>
      <p>Piano samples: Salamander Grand Piano by Alexander Holm (CC BY 3.0)</p>
    </footer>
  );
}

function NotFound() {
  return (
    <div className="page narrow">
      <h1>Page not found</h1>
      <p>
        <Link to="/">Go to your songs</Link>
      </p>
    </div>
  );
}

export function App() {
  return (
    <AuthProvider>
      <div className="app">
        <Header />
        <main className="main">
          <Routes>
            <Route path="/login" element={<AuthPage mode="login" />} />
            <Route path="/register" element={<AuthPage mode="register" />} />
            <Route
              path="/"
              element={
                <RequireAuth>
                  <LibraryPage />
                </RequireAuth>
              }
            />
            <Route
              path="/new"
              element={
                <RequireAuth>
                  <NewSongPage />
                </RequireAuth>
              }
            />
            <Route
              path="/songs/:id"
              element={
                <RequireAuth>
                  <SongPage />
                </RequireAuth>
              }
            />
            <Route
              path="/admin/reports"
              element={
                <RequireAuth admin>
                  <AdminReportsPage />
                </RequireAuth>
              }
            />
            <Route path="/s/:slug" element={<SharedPage />} />
            <Route path="/legal/rights" element={<RightsPage />} />
            <Route path="/legal/takedown" element={<TakedownPage />} />
            <Route path="/library" element={<Navigate to="/" replace />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </main>
        <Footer />
      </div>
    </AuthProvider>
  );
}
