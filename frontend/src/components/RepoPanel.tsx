import { Globe, Lock, Play } from "lucide-react";
import type { Branch, JobStatus, Repo } from "../types/graph";
import Combobox from "./Combobox";

interface Props {
  repos: Repo[];
  reposLoading: boolean;
  repo: Repo | null;
  repoVisibility: "public" | "private";
  branches: Branch[];
  branchesLoading: boolean;
  branch: Branch | null;
  job: JobStatus | null;
  error: string | null;
  busy: boolean;
  onRepo: (r: Repo) => void;
  onBranch: (b: Branch) => void;
  onGenerate: (force: boolean) => void;
}

export default function RepoPanel(p: Props) {
  const running = p.job?.state === "queued" || p.job?.state === "running";
  return (
    <div className="repo-panel">
      <div className="field">
        <label>{p.repoVisibility === "private" ? "Private repositories" : "Public repositories"}</label>
        <Combobox
          items={p.repos} value={p.repo} loading={p.reposLoading} placeholder="Select a repository"
          getKey={(r) => r.full_name} getText={(r) => r.full_name} onChange={p.onRepo}
          render={(r) => (
            <span className="repo-row">
              {r.private ? <Lock size={13} /> : <Globe size={13} />}
              <b>{r.name}</b><span className="muted">{r.owner} · {r.visibility} · {r.default_branch}</span>
            </span>
          )}
        />
        <small className="muted">Showing {p.repoVisibility} repositories only. To switch visibility, disconnect and reconnect with the other access option.</small>
      </div>
      <div className="field">
        <label>Branch</label>
        <Combobox
          items={p.branches} value={p.branch} loading={p.branchesLoading} disabled={!p.repo}
          placeholder="Select a branch" getKey={(b) => b.name} getText={(b) => b.name} onChange={p.onBranch}
          render={(b) => <span>{b.name}{b.protected ? " 🔒" : ""}</span>}
        />
      </div>
      <button className="btn primary" disabled={!p.repo || !p.branch || p.busy || running} onClick={() => p.onGenerate(false)}>
        <Play size={15} /> Generate Code Graph
      </button>
      {p.job && p.job.state !== "idle" && (
        <div className="progress">
          {running && (
            <>
              <div className="bar"><div style={{ width: `${p.job.percent}%` }} /></div>
              <small>{p.job.message || p.job.stage} ({Math.round(p.job.percent)}%)</small>
            </>
          )}
          {p.job.state === "ready" && (
            <small className="ok">
              {p.job.cached ? "Already indexed for this commit — loaded from cache." : "Graph ready."}{" "}
              {p.job.commit_sha && <code>{p.job.commit_sha.slice(0, 8)}</code>}{" "}
              <button className="link" onClick={() => p.onGenerate(true)}>Re-index</button>
            </small>
          )}
          {p.job.state === "failed" && <div className="alert error">{p.job.error?.message ?? "Indexing failed."}</div>}
        </div>
      )}
      {p.error && <div className="alert error">{p.error}</div>}
    </div>
  );
}
