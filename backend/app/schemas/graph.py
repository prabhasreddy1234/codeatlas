from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1

NodeType = Literal[
    "repository", "package", "file", "layout", "class", "interface", "object",
    "enum", "annotation", "function", "constructor",
]
EdgeType = Literal[
    "CONTAINS", "IMPORTS", "CALLS", "EXTENDS", "IMPLEMENTS", "OVERRIDES",
    "USES", "INJECTS", "NAVIGATES_TO", "DECLARES",
]
# confirmed: resolved to a repo declaration via package/import/declaration index.
# inferred: resolved by a heuristic (unique simple name, naming convention, overload guess).
# external: resolved to a fully-qualified symbol outside the repository (SDK/library).
# unresolved: target could not be determined; never linked to a node.
Resolution = Literal["confirmed", "inferred", "external", "unresolved"]


class GraphNode(BaseModel):
    id: str
    type: NodeType
    roles: list[str] = Field(default_factory=list)
    role_evidence: dict[str, str] = Field(default_factory=dict)
    name: str
    qualified_name: str
    file_path: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    language: Optional[str] = None
    package: Optional[str] = None
    parent_id: Optional[str] = None
    signature: Optional[str] = None
    modifiers: list[str] = Field(default_factory=list)
    annotations: list[str] = Field(default_factory=list)


class GraphEdge(BaseModel):
    id: str
    type: EdgeType
    source: str
    target: Optional[str] = None
    target_name: Optional[str] = None
    status: Resolution = "confirmed"
    provenance: str = ""
    file_path: Optional[str] = None
    line: Optional[int] = None
    lines: list[int] = Field(default_factory=list)
    count: int = 1


class RepositoryInfo(BaseModel):
    id: str
    owner: str
    name: str


class AnalyzerInfo(BaseModel):
    name: str = "codeatlas-static"
    version: str = "0.1.0"
    resolver: str = "tree-sitter + symbol index (no compiler semantics)"
    llm_used: bool = False


class GraphDocument(BaseModel):
    schema_version: int = SCHEMA_VERSION
    repository: RepositoryInfo
    branch: str
    commit_sha: str
    indexed_at: str
    analyzer: AnalyzerInfo = Field(default_factory=AnalyzerInfo)
    stats: dict = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class GenerateRequest(BaseModel):
    owner: str
    repo: str
    branch: str
    force: bool = False


class JobStatus(BaseModel):
    state: Literal["idle", "queued", "running", "ready", "failed"] = "idle"
    stage: str = ""
    percent: int = 0
    message: str = ""
    files_total: int = 0
    files_done: int = 0
    commit_sha: Optional[str] = None
    cached: bool = False
    error: Optional[dict] = None
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
