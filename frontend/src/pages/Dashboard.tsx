import {
  useCallback, useEffect, useMemo, useRef, useState,
  type CSSProperties, type KeyboardEvent, type PointerEvent,
} from "react";
import { ReactFlowProvider } from "@xyflow/react";
import {
  ArrowLeftRight, ArrowDownUp, Expand, PanelLeftClose, PanelLeftOpen, PanelRightClose,
  PanelRightOpen, Search, Shrink,
} from "lucide-react";
import { api, ApiError } from "../api/client";
import type { Branch, EdgeType, GEdge, GNode, GraphMeta, JobStatus, NodeDetails, Repo } from "../types/graph";
import type { Direction } from "../graph/layout";
import { ALL_EDGE_TYPES, DEFAULT_EDGE_TYPES, EDGE_STYLE, NODE_FILTERS } from "../graph/style";
import RepoPanel from "../components/RepoPanel";
import GraphCanvas from "../components/GraphCanvas";
import Inspector from "../components/Inspector";
import Legend from "../components/Legend";
import ChatPanel from "../components/ChatPanel";

const msg = (e: unknown) => (e instanceof ApiError ? e.message : "Unexpected error");

interface Props {
  privateAccess: boolean;
  onSelection: (repo?: string, branch?: string) => void;
}

export default function Dashboard({ privateAccess, onSelection }: Props) {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [sidebarWidth, setSidebarWidth] = useState(320);
  const [inspectorWidth, setInspectorWidth] = useState(360);
  const [fullscreen, setFullscreen] = useState(false);
  const canvasShell = useRef<HTMLDivElement>(null);
  const dashRef = useRef<HTMLDivElement>(null);
  const [visibility, setVisibility] = useState<"public" | "private">("public");
  const [repos, setRepos] = useState<Repo[]>([]);
  const [reposLoading, setReposLoading] = useState(true);
  const [repo, setRepo] = useState<Repo | null>(null);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [branchesLoading, setBranchesLoading] = useState(false);
  const [branch, setBranch] = useState<Branch | null>(null);
  const [job, setJob] = useState<JobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [meta, setMeta] = useState<GraphMeta | null>(null);
  const [nodes, setNodes] = useState<Map<string, GNode>>(new Map());
  const [edges, setEdges] = useState<Map<string, GEdge>>(new Map());
  const [focus, setFocus] = useState<Set<string> | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [details, setDetails] = useState<NodeDetails | null>(null);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [direction, setDirection] = useState<Direction>("LR");
  const [typeFilter, setTypeFilter] = useState<Set<string>>(new Set(NODE_FILTERS));
  const [edgeFilter, setEdgeFilter] = useState<Set<EdgeType>>(new Set(DEFAULT_EDGE_TYPES));
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<GNode[]>([]);
  const [matchIds, setMatchIds] = useState<Set<string>>(new Set());
  const [showLegend, setShowLegend] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);

  const owner = repo?.owner;
  const name = repo?.name;
  const br = branch?.name;

  useEffect(() => {
    const syncFullscreen = () => setFullscreen(document.fullscreenElement === canvasShell.current);
    document.addEventListener("fullscreenchange", syncFullscreen);
    return () => document.removeEventListener("fullscreenchange", syncFullscreen);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setReposLoading(true);
    api.repos(visibility)
      .then((items) => { if (!cancelled) setRepos(items); })
      .catch((e) => { if (!cancelled) setError(msg(e)); })
      .finally(() => { if (!cancelled) setReposLoading(false); });
    return () => { cancelled = true; };
  }, [visibility]);

  useEffect(() => () => eventSourceRef.current?.close(), []);

  useEffect(() => { onSelection(repo?.full_name, branch?.name); }, [repo, branch, onSelection]);

  const resetGraph = () => {
    setMeta(null); setNodes(new Map()); setEdges(new Map()); setFocus(null);
    setSelectedId(null); setDetails(null); setResults([]); setMatchIds(new Set()); setQuery("");
  };

  const changeVisibility = (next: "public" | "private") => {
    if (next === visibility) return;
    setVisibility(next);
    setRepos([]);
    setRepo(null); setBranch(null); setBranches([]); setJob(null); setError(null);
    setBranchesLoading(false);
    setBusy(false);
    eventSourceRef.current?.close();
    resetGraph();
  };

  const pickRepo = (r: Repo) => {
    setRepo(r); setBranch(null); setBranches([]); setJob(null); setError(null); resetGraph();
    setBusy(false);
    eventSourceRef.current?.close();
    setBranchesLoading(true);
    api.branches(r.owner, r.name)
      .then((bs) => {
        setBranches(bs);
        setBranch(bs.find((b) => b.name === r.default_branch) ?? bs[0] ?? null);
      })
      .catch((e) => setError(msg(e)))
      .finally(() => setBranchesLoading(false));
  };

  const loadGraph = useCallback(async (o: string, n: string, b: string) => {
    const g = await api.graph(o, n, b);
    setMeta(g);
    setNodes(new Map(g.overview.nodes.map((x) => [x.id, x])));
    setEdges(new Map(g.overview.edges.map((x) => [x.id, x])));
    setFocus(null); setSelectedId(null); setDetails(null);
  }, []);

  const watch = useCallback((o: string, n: string, b: string) => {
    eventSourceRef.current?.close();
    const es = new EventSource(`/api/graphs/${o}/${n}/stream?${new URLSearchParams({ branch: b }).toString()}`);
    eventSourceRef.current = es;

    es.onmessage = async (event) => {
      try {
        const s: JobStatus = JSON.parse(event.data);
        setJob(s);
        if (s.nodes && s.nodes.length > 0) {
          merge({ nodes: s.nodes, edges: s.edges || [] });
        }
        if (s.state === "ready") {
          es.close();
          await loadGraph(o, n, b);
          setBusy(false);
        } else if (s.state === "failed") {
          es.close();
          setError(s.error?.message ?? "Graph generation failed.");
          setBusy(false);
        }
      } catch (e) {
        console.error("SSE parse error", e);
      }
    };

    es.onerror = () => {
      setError("Graph updates were interrupted. Please try generating the graph again.");
      es.close();
      setBusy(false);
    };
  }, [loadGraph]);

  const generate = async (force: boolean) => {
    if (!owner || !name || !br) return;
    setError(null); setBusy(true); resetGraph();
    eventSourceRef.current?.close();
    try {
      const status = await api.generate(owner, name, br, force);
      setJob(status);
      if (status.nodes?.length) {
        merge({ nodes: status.nodes, edges: status.edges ?? [] });
      }
      if (status.state === "ready") {
        await loadGraph(owner, name, br);
        setBusy(false);
      } else if (status.state === "failed") {
        setError(status.error?.message ?? "Graph generation failed.");
        setBusy(false);
      } else {
        watch(owner, name, br);
      }
    } catch (e) {
      setError(msg(e));
      setBusy(false);
    }
  };

  const merge = (chunk: { nodes: GNode[]; edges: GEdge[] }) => {
    setNodes((m) => { const c = new Map(m); chunk.nodes.forEach((x) => c.set(x.id, x)); return c; });
    setEdges((m) => { const c = new Map(m); chunk.edges.forEach((x) => c.set(x.id, x)); return c; });
  };

  const select = useCallback((id: string | null) => {
    setSelectedId(id);
    if (!id || !owner || !name || !br) { setDetails(null); return; }
    setDetailsLoading(true);
    api.node(owner, name, br, id).then(setDetails).catch((e) => setError(msg(e))).finally(() => setDetailsLoading(false));
  }, [owner, name, br]);

  const expand = async (id: string, direction: "in" | "out" | "both", members = false) => {
    if (!owner || !name || !br) return;
    try {
      const chunk = await api.neighbors(owner, name, br, id, { direction, depth: 1, members });
      merge(chunk);
      setFocus((f) => new Set([...(f ?? [id]), id, ...chunk.nodes.map((n) => n.id)]));
    } catch (e) { setError(msg(e)); }
  };

  const hideUnrelated = async (id: string) => {
    if (!owner || !name || !br) return;
    try {
      const chunk = await api.neighbors(owner, name, br, id, { direction: "both", depth: 1 });
      merge(chunk);
      setFocus(new Set([id, ...chunk.nodes.map((n) => n.id)]));
      setSelectedId(id);
    } catch (e) { setError(msg(e)); }
  };

  const runSearch = async () => {
    if (!owner || !name || !br || !query.trim()) { setResults([]); setMatchIds(new Set()); return; }
    try {
      const r = await api.search(owner, name, br, query.trim());
      setResults(r); setMatchIds(new Set(r.map((x) => x.id)));
    } catch (e) { setError(msg(e)); }
  };

  const showResult = async (n: GNode) => {
    merge({ nodes: [n], edges: [] });
    setResults([]);
    await expand(n.id, "both");
    select(n.id);
  };

  const backToOverview = () => {
    if (!meta) return;
    setNodes(new Map(meta.overview.nodes.map((x) => [x.id, x])));
    setEdges(new Map(meta.overview.edges.map((x) => [x.id, x])));
    setFocus(null); setSelectedId(null); setDetails(null); setMatchIds(new Set());
  };

  const toggle = <T,>(set: Set<T>, v: T, apply: (s: Set<T>) => void) => {
    const c = new Set(set);
    if (c.has(v)) c.delete(v); else c.add(v);
    apply(c);
  };

  const toggleFullscreen = async () => {
    try {
      if (document.fullscreenElement === canvasShell.current) {
        await document.exitFullscreen();
      } else {
        await canvasShell.current?.requestFullscreen();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not change fullscreen mode.");
    }
  };

  const resizeSidebar = (event: PointerEvent<HTMLDivElement>) => {
    if (event.buttons === 1) setSidebarWidth(Math.min(520, Math.max(220, event.clientX - (dashRef.current?.getBoundingClientRect().left ?? 0))));
  };

  const resizeInspector = (event: PointerEvent<HTMLDivElement>) => {
    if (event.buttons === 1) {
      const right = dashRef.current?.getBoundingClientRect().right ?? window.innerWidth;
      setInspectorWidth(Math.min(600, Math.max(260, right - event.clientX)));
    }
  };

  const adjustPanelWidth = (panel: "sidebar" | "inspector", event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const delta = event.key === "ArrowRight" ? 16 : -16;
    if (panel === "sidebar") setSidebarWidth((width) => Math.min(520, Math.max(220, width + delta)));
    else setInspectorWidth((width) => Math.min(600, Math.max(260, width - delta)));
  };

  const visNodes = useMemo(
    () => [...nodes.values()].filter((n) => (typeFilter.has(n.type) || n.type === "repository" || busy) && (!focus || focus.has(n.id))),
    [nodes, typeFilter, focus, busy],
  );
  const visEdges = useMemo(() => {
    const ids = new Set(visNodes.map((n) => n.id));
    return [...edges.values()].filter((e) => edgeFilter.has(e.type) && e.target && ids.has(e.source) && ids.has(e.target));
  }, [edges, edgeFilter, visNodes]);
  const graphVisible = meta !== null || busy;

  return (
    <div className="dashboard-split">
      <section className="dashboard-content" aria-label="Code graph workspace">
        <div
          ref={dashRef}
          className={`dash${sidebarOpen ? "" : " sidebar-collapsed"}${inspectorOpen && meta ? "" : " inspector-collapsed"}`}
          style={{ "--sidebar-width": `${sidebarWidth}px`, "--inspector-width": `${inspectorWidth}px` } as CSSProperties}
        >
      <div className="sidebar" hidden={!sidebarOpen}>
        <RepoPanel
          repos={repos} reposLoading={reposLoading} visibility={visibility} privateAccess={privateAccess}
          onVisibility={changeVisibility} repo={repo} branches={branches}
          branchesLoading={branchesLoading} branch={branch} job={job} error={error} busy={busy}
          onRepo={pickRepo} onBranch={(b) => {
            eventSourceRef.current?.close();
            setBusy(false); setBranch(b); setJob(null); resetGraph();
          }} onGenerate={generate}
        />
        {meta && (
          <>
            <div className="meta-box">
              <div><b>Commit</b> <code>{meta.commit_sha.slice(0, 10)}</code></div>
              <div><b>Indexed</b> {new Date(meta.indexed_at).toLocaleString()}</div>
              <div><b>Source files</b> {meta.stats.source_files ?? 0} · <b>Nodes</b> {meta.stats.nodes ?? "?"} · <b>Edges</b> {meta.stats.edges ?? "?"}</div>
              <div className="muted">Analyzer: {meta.analyzer.name} {meta.analyzer.version} · LLM used: no</div>
              {meta.warnings.length > 0 && <details><summary>{meta.warnings.length} warning(s)</summary>{meta.warnings.slice(0, 20).map((w, i) => <div key={i} className="muted">{w}</div>)}</details>}
            </div>
            <div className="filters">
              <h4>Node types</h4>
              <div className="chips">
                {NODE_FILTERS.map((t) => (
                  <label key={t} className={`chip${typeFilter.has(t) ? " on" : ""}`}>
                    <input type="checkbox" checked={typeFilter.has(t)} onChange={() => toggle(typeFilter, t, setTypeFilter)} />{t}
                  </label>
                ))}
              </div>
              <h4>Relationships</h4>
              <div className="chips">
                {ALL_EDGE_TYPES.map((t) => (
                  <label key={t} className={`chip${edgeFilter.has(t) ? " on" : ""}`} style={edgeFilter.has(t) ? { borderColor: EDGE_STYLE[t].color } : undefined}>
                    <input type="checkbox" checked={edgeFilter.has(t)} onChange={() => toggle(edgeFilter, t, setEdgeFilter)} />{EDGE_STYLE[t].label}
                  </label>
                ))}
              </div>
            </div>
          </>
        )}
        <button className="ghost" onClick={() => setShowLegend((s) => !s)}>{showLegend ? "Hide" : "Show"} legend</button>
        {showLegend && <Legend />}
      </div>
      {sidebarOpen && (
        <div
          className="panel-resizer sidebar-resizer"
          role="separator"
          aria-label="Resize repository sidebar"
          aria-orientation="vertical"
          aria-valuemin={220}
          aria-valuemax={520}
          aria-valuenow={sidebarWidth}
          tabIndex={0}
          onPointerDown={(event) => event.currentTarget.setPointerCapture(event.pointerId)}
          onPointerMove={resizeSidebar}
          onKeyDown={(event) => adjustPanelWidth("sidebar", event)}
        />
      )}

      <main className="workspace">
        <div className="panel-togglebar">
          <button className="ghost" onClick={() => setSidebarOpen((open) => !open)}
                  aria-label={sidebarOpen ? "Collapse repository sidebar" : "Expand repository sidebar"}
                  title={sidebarOpen ? "Collapse repository sidebar" : "Expand repository sidebar"}>
            {sidebarOpen ? <PanelLeftClose size={15} /> : <PanelLeftOpen size={15} />}
          </button>
          <button className="ghost" onClick={() => setInspectorOpen((open) => !open)} disabled={!meta}
                  aria-label={inspectorOpen ? "Collapse inspector panel" : "Expand inspector panel"}
                  title={inspectorOpen ? "Collapse inspector panel" : "Expand inspector panel"}>
            {inspectorOpen ? <PanelRightClose size={15} /> : <PanelRightOpen size={15} />}
          </button>
        </div>
        {graphVisible ? (
          <>
            <div className="toolbar">
              {meta && (
                <div className="search">
                  <Search size={14} />
                  <input value={query} placeholder="Search class, interface, method or file…"
                         onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && runSearch()} />
                  {results.length > 0 && (
                    <div className="search-pop">
                      {results.map((r) => (
                        <div key={r.id} className="combo-item" onClick={() => showResult(r)}>
                          <b>{r.name}</b> <span className="muted">{r.type} · {r.file_path}{r.start_line ? `:${r.start_line}` : ""}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
              <button className="ghost" onClick={() => setDirection((d) => (d === "LR" ? "TB" : "LR"))} title="Toggle layout direction">
                {direction === "LR" ? <ArrowLeftRight size={14} /> : <ArrowDownUp size={14} />} {direction === "LR" ? "Left → right" : "Top → bottom"}
              </button>
              {focus && <button className="ghost" onClick={() => setFocus(null)}>Show all loaded nodes</button>}
              {meta && <button className="ghost" onClick={backToOverview}>Overview</button>}
              <span className="muted">
                {busy && job?.message ? `${job.message} · ` : ""}
                {visNodes.length} nodes · {visEdges.length} edges
                {meta?.overview.truncated ? " · overview truncated to top entries" : ""}
              </span>
            </div>
            <div className="canvas-shell" ref={canvasShell}>
              <button className="ghost fullscreen-toggle" onClick={toggleFullscreen}
                      aria-label={fullscreen ? "Exit fullscreen" : "Open canvas fullscreen"}
                      title={fullscreen ? "Exit fullscreen" : "Open canvas fullscreen"}>
                {fullscreen ? <Shrink size={15} /> : <Expand size={15} />}
                {fullscreen ? "Exit fullscreen" : "Fullscreen"}
              </button>
              <div className="canvas">
              {visNodes.length === 0 ? (
                <div className="canvas-empty">
                  <div>
                    {busy ? (
                      <>
                        <h2>Building graph…</h2>
                        <p className="muted">{job?.message || "Preparing source files for analysis."}</p>
                      </>
                    ) : meta?.overview.nodes.length === 0 ? (
                      <>
                        <h2>No code graph to display</h2>
                        <p>
                          CodeAtlas currently graphs Python, Kotlin, and Java source files. This branch has{" "}
                          {meta?.stats.source_files ?? 0} supported source files.
                        </p>
                        {meta?.warnings[0] && <p className="muted">{meta.warnings[0]}</p>}
                        <p className="muted">Choose a branch or repository containing Python, Kotlin, or Java code, then generate the graph again.</p>
                      </>
                    ) : (
                      <>
                        <h2>No nodes match the current filters</h2>
                        <p className="muted">Enable one or more node types in the sidebar to show the graph.</p>
                      </>
                    )}
                  </div>
                </div>
              ) : (
                <ReactFlowProvider>
                  <GraphCanvas
                    nodes={visNodes} edges={visEdges} selectedId={selectedId} matchIds={matchIds}
                    direction={direction} onSelect={select} onReset={backToOverview}
                  />
                </ReactFlowProvider>
              )}
              </div>
            </div>
          </>
        ) : (
          <div className="placeholder">
            <p>Select a repository and branch, then click <b>Generate Code Graph</b>.</p>
          </div>
        )}
      </main>

      {meta && inspectorOpen && (
        <div
          className="panel-resizer inspector-resizer"
          role="separator"
          aria-label="Resize inspector panel"
          aria-orientation="vertical"
          aria-valuemin={260}
          aria-valuemax={600}
          aria-valuenow={inspectorWidth}
          tabIndex={0}
          onPointerDown={(event) => event.currentTarget.setPointerCapture(event.pointerId)}
          onPointerMove={resizeInspector}
          onKeyDown={(event) => adjustPanelWidth("inspector", event)}
        />
      )}

      {meta && inspectorOpen && (
        <Inspector
          details={details} loading={detailsLoading} onClose={() => select(null)}
          onMembers={(id) => expand(id, "both", true)}
          onFocus={hideUnrelated} onSelect={(id) => { select(id); if (!nodes.has(id)) expand(id, "both"); }}
        />
      )}
        </div>
      </section>
      <ChatPanel
        repository={repo?.full_name ?? null}
        branch={branch?.name ?? null}
        graph={meta}
        nodes={[...nodes.values()]}
        edges={[...edges.values()]}
      />
    </div>
  );
}
