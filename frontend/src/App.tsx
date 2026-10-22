import { useCallback, useEffect, useState } from "react";
import { Network } from "lucide-react";
import { api, setCsrf } from "./api/client";
import type { Me } from "./types/graph";
import Header from "./components/Header";
import ConnectPage from "./pages/ConnectPage";
import Dashboard from "./pages/Dashboard";
import OrbLoader from "./components/OrbLoader";

type Theme = "light" | "dark";

export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [down, setDown] = useState(false);
  const [sel, setSel] = useState<{ repo?: string; branch?: string }>({});
  const [theme, setTheme] = useState<Theme>(() => {
    const saved = window.localStorage.getItem("codeatlas-theme");
    if (saved === "light" || saved === "dark") return saved;
    return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  });

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    window.localStorage.setItem("codeatlas-theme", theme);
  }, [theme]);

  useEffect(() => {
    api.me().then((m) => { setCsrf(m.csrf_token ?? ""); setMe(m); }).catch(() => setDown(true));
  }, []);

  const onSelection = useCallback((repo?: string, branch?: string) => setSel({ repo, branch }), []);

  const logout = async () => {
    await api.logout().catch(() => undefined);
    window.location.href = "/";
  };

  if (down) return (
    <div className="connect">
      <div className="connect-card">
        <div className="brand-mark"><Network size={42} /></div>
        <p className="eyebrow">Service unavailable</p>
        <h1>CodeAtlas is offline</h1>
        <p>Cannot reach the backend on port 8000. Start it first, then refresh this page.</p>
        <div className="alert error">The API was not reachable on localhost:8000. Check the backend process and README instructions.</div>
        <a className="btn primary" href="/">Reload</a>
      </div>
    </div>
  );
  if (!me) return (
    <div className="connect">
      <div className="connect-card loading-shell">
        <OrbLoader />
        <p className="eyebrow">Preparing workspace</p>
        <h1>Loading CodeAtlas…</h1>
      </div>
    </div>
  );
  if (!me.authenticated) return <><Header me={me} theme={theme} onToggleTheme={() => setTheme((current) => current === "dark" ? "light" : "dark")} onLogout={logout} /><ConnectPage me={me} /></>;
  return (
    <div className="app">
      <Header me={me} repo={sel.repo} branch={sel.branch} theme={theme} onToggleTheme={() => setTheme((current) => current === "dark" ? "light" : "dark")} onLogout={logout} />
      <Dashboard privateAccess={Boolean(me.private_access)} onSelection={onSelection} />
    </div>
  );
}
