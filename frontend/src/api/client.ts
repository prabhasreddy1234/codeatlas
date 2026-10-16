import type {
  Branch, GraphChunk, GraphDocument, GraphMeta, JobStatus, Me, NodeDetails, Repo, GNode,
} from "../types/graph";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

let csrfToken = "";
export const setCsrf = (t: string) => { csrfToken = t; };

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (init.method && init.method !== "GET") {
    headers["Content-Type"] = "application/json";
    headers["X-CSRF-Token"] = csrfToken;
  }
  let res: Response;
  try {
    res = await fetch(path, { credentials: "same-origin", ...init, headers });
  } catch {
    throw new ApiError(0, "network", "Cannot reach the CodeAtlas backend. Is it running on port 8000?");
  }
  if (!res.ok) {
    let code = "http_error";
    let msg = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      code = body.error?.code ?? code;
      msg = body.error?.message ?? msg;
    } catch { /* non-JSON error */ }
    throw new ApiError(res.status, code, msg);
  }
  return res.json() as Promise<T>;
}

const q = (o: Record<string, string | number | boolean | undefined>) =>
  new URLSearchParams(Object.entries(o).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)])).toString();

export const api = {
  me: () => request<Me>("/api/auth/me"),
  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
  repos: (visibility: "public" | "private" = "public") =>
    request<{ repositories: Repo[] }>(`/api/github/repos?${q({ visibility })}`).then((r) => r.repositories),
  branches: (owner: string, repo: string) =>
    request<{ branches: Branch[] }>(`/api/github/repos/${owner}/${repo}/branches`).then((r) => r.branches),
  generate: (owner: string, repo: string, branch: string, force = false) =>
    request<JobStatus>("/api/graphs/generate", { method: "POST", body: JSON.stringify({ owner, repo, branch, force }) }),
  status: (owner: string, repo: string, branch: string) =>
    request<JobStatus>(`/api/graphs/${owner}/${repo}/status?${q({ branch })}`),
  graph: (owner: string, repo: string, branch: string, limit = 120) =>
    request<GraphMeta>(`/api/graphs/${owner}/${repo}?${q({ branch, limit })}`),
  graphExport: (owner: string, repo: string, branch: string) =>
    request<GraphDocument>(`/api/graphs/${owner}/${repo}/export?${q({ branch })}`),
  search: (owner: string, repo: string, branch: string, text: string) =>
    request<{ results: GNode[] }>(`/api/graphs/${owner}/${repo}/search?${q({ branch, q: text })}`).then((r) => r.results),
  node: (owner: string, repo: string, branch: string, id: string) =>
    request<NodeDetails>(`/api/graphs/${owner}/${repo}/nodes/${encodeURIComponent(id)}?${q({ branch })}`),
  neighbors: (owner: string, repo: string, branch: string, id: string,
              opts: { direction?: "in" | "out" | "both"; depth?: number; members?: boolean } = {}) =>
    request<GraphChunk>(`/api/graphs/${owner}/${repo}/neighbors/${encodeURIComponent(id)}?${q({ branch, ...opts })}`),
};
