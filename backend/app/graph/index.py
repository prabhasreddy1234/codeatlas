"""In-memory query layer over a stored GraphDocument (overview, neighbors, search)."""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Optional

from ..schemas.graph import GraphDocument, GraphEdge, GraphNode

CLASS_LIKE = {"class", "interface", "object", "enum", "annotation"}
LIFTED_TYPES = {"CALLS", "USES", "EXTENDS", "IMPLEMENTS", "INJECTS", "NAVIGATES_TO", "OVERRIDES"}
ROLE_ORDER = ["activity", "fragment", "composable", "viewmodel", "repository", "dao",
              "worker", "service", "receiver"]


class GraphIndex:
    def __init__(self, doc: GraphDocument):
        self.doc = doc
        self.nodes: dict[str, GraphNode] = {n.id: n for n in doc.nodes}
        self.out: dict[str, list[GraphEdge]] = defaultdict(list)
        self.inc: dict[str, list[GraphEdge]] = defaultdict(list)
        self.children: dict[str, list[str]] = defaultdict(list)
        for e in doc.edges:
            self.out[e.source].append(e)
            if e.target:
                self.inc[e.target].append(e)
            if e.type == "CONTAINS" and e.target:
                self.children[e.source].append(e.target)
        self._lift_cache: dict[str, Optional[str]] = {}

    def _is_python_top_level_function(self, node: GraphNode) -> bool:
        parent = self.nodes.get(node.parent_id) if node.parent_id else None
        return (
            node.language == "python"
            and node.type in ("function", "constructor")
            and parent is not None
            and parent.type == "file"
        )

    @staticmethod
    def _is_class_level_node(node: GraphNode) -> bool:
        return node.type in CLASS_LIKE or "composable" in node.roles

    # ---- helpers -----------------------------------------------------------
    def lift(self, node_id: str) -> Optional[str]:
        """Nearest class-level entity for a node (class, or composable function)."""
        if node_id in self._lift_cache:
            return self._lift_cache[node_id]
        cur, res = self.nodes.get(node_id), None
        while cur is not None:
            if self._is_python_top_level_function(cur):
                res = cur.id
                break
            if self._is_class_level_node(cur):
                res = cur.id
                break
            if cur.type in ("file", "package", "repository", "layout"):
                res = cur.id if cur.type == "layout" else None
                break
            cur = self.nodes.get(cur.parent_id) if cur.parent_id else None
        self._lift_cache[node_id] = res
        return res

    def lifted_edges(self, types: Optional[set[str]] = None, include_inferred: bool = True) -> list[dict]:
        agg: dict[tuple, dict] = {}
        for e in self.doc.edges:
            if e.type not in LIFTED_TYPES or not e.target:
                continue
            if types and e.type not in types:
                continue
            s, t = self.lift(e.source), self.lift(e.target)
            if not s or not t or s == t:
                continue
            k = (s, t, e.type)
            a = agg.get(k)
            if a is None:
                agg[k] = {"id": f"L:{s}:{t}:{e.type}", "type": e.type, "source": s, "target": t,
                          "status": e.status, "count": e.count, "provenance": e.provenance,
                          "file_path": e.file_path, "line": e.line, "lifted": True}
            else:
                a["count"] += e.count
                if e.status == "inferred" and a["status"] == "confirmed":
                    a["status"] = "inferred"
        return list(agg.values())

    def node_dict(self, n: GraphNode) -> dict:
        d = n.model_dump()
        d["degree"] = len(self.out.get(n.id, [])) + len(self.inc.get(n.id, []))
        return d

    # ---- overview ------------------------------------------------------------
    def overview(self, limit: int = 120) -> dict:
        lifted = self.lifted_edges()
        adj: dict[str, set[str]] = defaultdict(set)
        for e in lifted:
            adj[e["source"]].add(e["target"])
            adj[e["target"]].add(e["source"])

        seeds = [n for n in self.doc.nodes
                 if (n.roles and (n.type in CLASS_LIKE or "composable" in n.roles))
                 or (n.language == "python"
                     and (n.type in CLASS_LIKE or self._is_python_top_level_function(n)))]
        seeds.sort(key=lambda n: (min((ROLE_ORDER.index(r) for r in n.roles if r in ROLE_ORDER), default=99),
                                  n.qualified_name))
        chosen: list[str] = [n.id for n in seeds]
        if not chosen:
            cands = [n for n in self.doc.nodes
                     if n.type in CLASS_LIKE or self._is_python_top_level_function(n)]
            cands.sort(key=lambda n: -len(adj.get(n.id, ())))
            chosen = [n.id for n in cands]
        chosen = chosen[:limit]
        sel = set(chosen)
        # add direct dependencies of the entry points until the limit is reached
        for nid in list(chosen):
            for e in lifted:
                if len(sel) >= limit:
                    break
                if e["source"] == nid and e["target"] not in sel and e["type"] != "USES":
                    sel.add(e["target"])
        edges = [e for e in lifted if e["source"] in sel and e["target"] in sel]
        total_candidates = sum(
            1 for n in self.doc.nodes
            if self._is_class_level_node(n) or self._is_python_top_level_function(n))
        return {"nodes": [self.node_dict(self.nodes[i]) for i in sel], "edges": edges,
                "total_class_level_nodes": total_candidates, "truncated": total_candidates > len(sel),
                "entry_points": len(seeds)}

    # ---- neighbors -------------------------------------------------------------
    def neighbors(self, node_id: str, direction: str = "both", depth: int = 1,
                  types: Optional[set[str]] = None, members: bool = False,
                  limit: int = 300) -> dict:
        node = self.nodes[node_id]
        nodes: dict[str, GraphNode] = {node_id: node}
        edges: dict[str, dict] = {}

        def add_edge(d: dict) -> None:
            edges[d["id"]] = d

        if node.type in ("repository", "package", "file") or members:
            for cid in self.children.get(node_id, []):
                c = self.nodes[cid]
                nodes[cid] = c
                if members and c.type in CLASS_LIKE:
                    continue
                add_edge({"id": f"C:{node_id}:{cid}", "type": "CONTAINS", "source": node_id,
                          "target": cid, "status": "confirmed", "count": 1})
            if members and node.type in CLASS_LIKE:
                member_ids = [m for m in self.children.get(node_id, [])]
                for mid in member_ids:
                    for e in self.out.get(mid, []):
                        if e.type in ("CALLS", "OVERRIDES") and e.target and (not types or e.type in types):
                            if e.target in self.nodes:
                                nodes[e.target] = self.nodes[e.target]
                                add_edge({**e.model_dump(), "lifted": False})
            if node.type in ("package", "file"):
                par = self.nodes.get(node.parent_id) if node.parent_id else None
                if par and not members:
                    nodes[par.id] = par
                    add_edge({"id": f"C:{par.id}:{node_id}", "type": "CONTAINS", "source": par.id,
                              "target": node_id, "status": "confirmed", "count": 1})
            return self._pack(nodes, edges, limit)

        class_level = self._is_class_level_node(node)
        frontier = {node_id}
        seen = {node_id}
        if class_level:
            lifted = self.lifted_edges(types)
            for _ in range(depth):
                nxt = set()
                for e in lifted:
                    if direction in ("out", "both") and e["source"] in frontier and e["target"] not in seen:
                        nxt.add(e["target"])
                        add_edge(e)
                    if direction in ("in", "both") and e["target"] in frontier and e["source"] not in seen:
                        nxt.add(e["source"])
                        add_edge(e)
                seen |= nxt
                frontier = nxt
            for nid in seen:
                nodes[nid] = self.nodes[nid]
            # keep edges among already-selected nodes for context
            for e in lifted:
                if e["source"] in seen and e["target"] in seen:
                    add_edge(e)
            return self._pack(nodes, edges, limit)

        for _ in range(depth):
            nxt = set()
            for nid in frontier:
                if direction in ("out", "both"):
                    for e in self.out.get(nid, []):
                        if e.target and e.type not in ("CONTAINS", "DECLARES", "IMPORTS") and (not types or e.type in types):
                            add_edge({**e.model_dump(), "lifted": False})
                            nxt.add(e.target)
                if direction in ("in", "both"):
                    for e in self.inc.get(nid, []):
                        if e.type not in ("CONTAINS", "DECLARES", "IMPORTS") and (not types or e.type in types):
                            add_edge({**e.model_dump(), "lifted": False})
                            nxt.add(e.source)
            nxt -= seen
            seen |= nxt
            frontier = nxt
        for nid in seen:
            nodes[nid] = self.nodes[nid]
        return self._pack(nodes, edges, limit)

    def _pack(self, nodes: dict[str, GraphNode], edges: dict[str, dict], limit: int) -> dict:
        ids = list(nodes)[:limit]
        keep = set(ids)
        return {"nodes": [self.node_dict(nodes[i]) for i in ids],
                "edges": [e for e in edges.values() if e["source"] in keep and e["target"] in keep],
                "truncated": len(nodes) > limit}

    # ---- details/search --------------------------------------------------------
    def details(self, node_id: str) -> dict:
        n = self.nodes[node_id]
        def view(e: GraphEdge, other_id: Optional[str]) -> dict:
            o = self.nodes.get(other_id) if other_id else None
            return {**e.model_dump(), "other": {"id": o.id, "name": o.name, "type": o.type,
                                                 "qualified_name": o.qualified_name} if o else None}
        outgoing = [view(e, e.target) for e in self.out.get(node_id, []) if e.type != "CONTAINS"]
        incoming = [view(e, e.source) for e in self.inc.get(node_id, []) if e.type != "CONTAINS"]
        parent = self.nodes.get(n.parent_id) if n.parent_id else None
        kids = [self.nodes[c] for c in self.children.get(node_id, [])]
        return {"node": n.model_dump(), "parent": parent.model_dump() if parent else None,
                "children": [{"id": c.id, "name": c.name, "type": c.type, "signature": c.signature,
                              "start_line": c.start_line} for c in kids][:300],
                "outgoing": outgoing[:500], "incoming": incoming[:500],
                "outgoing_total": len(outgoing), "incoming_total": len(incoming)}

    def search(self, q: str, types: Optional[Iterable[str]] = None, limit: int = 40) -> list[dict]:
        ql = q.lower().strip()
        if not ql:
            return []
        tset = set(types) if types else None
        scored = []
        for n in self.doc.nodes:
            if n.type in ("repository",) or (tset and n.type not in tset):
                continue
            name, qn, fp = n.name.lower(), n.qualified_name.lower(), (n.file_path or "").lower()
            if name == ql:
                s = 0
            elif name.startswith(ql):
                s = 1
            elif ql in name:
                s = 2
            elif ql in qn:
                s = 3
            elif ql in fp:
                s = 4
            else:
                continue
            scored.append((s, len(name), n))
        scored.sort(key=lambda x: (x[0], x[1], x[2].qualified_name))
        return [self.node_dict(n) for _, _, n in scored[:limit]]
