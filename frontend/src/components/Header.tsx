import { LogOut, Network } from "lucide-react";
import { GithubLogo } from "../graph/style";
import type { Me } from "../types/graph";

interface Props { me: Me; repo?: string; branch?: string; onLogout: () => void }

export default function Header({ me, repo, branch, onLogout }: Props) {
  return (
    <header className="header">
      <div className="brand"><Network size={22} color="#3ddc84" /><span>CodeAtlas</span></div>
      <div className="header-mid">
        {repo && <span className="pill">{repo}</span>}
        {branch && <span className="pill alt">{branch}</span>}
      </div>
      <div className="header-right">
        {me.authenticated ? (
          <>
            <span className="status ok"><GithubLogo size={14} color="currentColor" /> Connected</span>
            {me.user?.avatar_url && <img className="avatar" src={me.user.avatar_url} alt="" />}
            <span className="user">@{me.user?.login}</span>
            <button className="ghost" onClick={onLogout} title="Disconnect GitHub"><LogOut size={14} /> Disconnect</button>
          </>
        ) : (
          <span className="status off">Not connected</span>
        )}
      </div>
    </header>
  );
}
