export type NodeType =
  | "repository" | "package" | "file" | "layout" | "class" | "interface" | "object"
  | "enum" | "annotation" | "function" | "constructor";

export type EdgeType =
  | "CONTAINS" | "IMPORTS" | "CALLS" | "EXTENDS" | "IMPLEMENTS" | "OVERRIDES"
  | "USES" | "INJECTS" | "NAVIGATES_TO" | "DECLARES";

export type Resolution = "confirmed" | "inferred" | "external" | "unresolved";

export interface GNode {
  id: string;
  type: NodeType;
  roles: string[];
  role_evidence: Record<string, string>;
  name: string;
  qualified_name: string;
  file_path?: string | null;
  start_line?: number | null;
  end_line?: number | null;
  language?: string | null;
  package?: string | null;
  parent_id?: string | null;
  signature?: string | null;
  modifiers: string[];
  annotations: string[];
  degree?: number;
}

export interface GEdge {
  id: string;
  type: EdgeType;
  source: string;
  target?: string | null;
  target_name?: string | null;
  status: Resolution;
  provenance?: string;
  file_path?: string | null;
  line?: number | null;
  lines?: number[];
  count: number;
  lifted?: boolean;
}

export interface GraphChunk {
  nodes: GNode[];
  edges: GEdge[];
  truncated?: boolean;
  total_class_level_nodes?: number;
  entry_points?: number;
}

export interface GraphMeta {
  repository: { id: string; owner: string; name: string };
  branch: string;
  commit_sha: string;
  indexed_at: string;
  analyzer: { name: string; version: string; resolver: string; llm_used: boolean };
  stats: Record<string, any>;
  warnings: string[];
  overview: GraphChunk;
}

export interface GraphDocument {
  schema_version: number;
  repository: GraphMeta["repository"];
  branch: string;
  commit_sha: string;
  indexed_at: string;
  analyzer: GraphMeta["analyzer"];
  stats: GraphMeta["stats"];
  warnings: string[];
  nodes: GNode[];
  edges: GEdge[];
}

export interface EdgeView extends GEdge {
  other: { id: string; name: string; type: NodeType; qualified_name: string } | null;
}

export interface NodeDetails {
  node: GNode;
  parent: GNode | null;
  children: { id: string; name: string; type: NodeType; signature?: string | null; start_line?: number | null }[];
  outgoing: EdgeView[];
  incoming: EdgeView[];
  outgoing_total: number;
  incoming_total: number;
}

export interface Repo {
  id: number;
  name: string;
  owner: string;
  full_name: string;
  private: boolean;
  visibility: string;
  default_branch: string;
  description?: string | null;
}

export interface Branch { name: string; commit_sha: string; protected: boolean }

export interface JobStatus {
  state: "idle" | "queued" | "running" | "ready" | "failed";
  stage: string;
  percent: number;
  message: string;
  files_total: number;
  files_done: number;
  commit_sha?: string | null;
  cached: boolean;
  error?: { code: string; message: string } | null;
  nodes?: GNode[];
  edges?: GEdge[];
}

export interface Me {
  authenticated: boolean;
  oauth_configured: boolean;
  csrf_token?: string;
  private_access?: boolean;
  scope?: string;
  user?: { login: string; name?: string | null; avatar_url?: string | null };
}
