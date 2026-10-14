import { useCallback, useEffect, useState } from "react";
import { api, setCsrf } from "./api/client";
import type { Me } from "./types/graph";
import Header from "./components/Header";
import ConnectPage from "./pages/ConnectPage";
import Dashboard from "./pages/Dashboard";

export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [down, setDown] = useState(false);
  const [sel, setSel] = useState<{ repo?: string; branch?: string }>({});

  useEffect(() => {
    api.me().then((m) => { setCsrf(m.csrf_token ?? ""); setMe(m); }).catch(() => setDown(true));
  }, []);

  const onSelection = useCallback((repo?: string, branch?: string) => setSel({ repo, branch }), []);

  const logout = async () => {
    await api.logout().catch(() => undefined);
    window.location.href = "/";
  };

  if (down) return <div className="connect"><div className="connect-card"><h1>CodeAtlas</h1><div className="alert error">Cannot reach the backend on port 8000. Start it first (see README).</div></div></div>;
  if (!me) return <div className="connect"><div className="connect-card">Loading…</div></div>;
  if (!me.authenticated) return <><Header me={me} onLogout={logout} /><ConnectPage me={me} /></>;
  return (
    <div className="app">
      <Header me={me} repo={sel.repo} branch={sel.branch} onLogout={logout} />
      <Dashboard privateAccess={Boolean(me.private_access)} onSelection={onSelection} />
    </div>
  );
}
