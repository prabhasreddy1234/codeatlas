"""In-memory query layer over a stored GraphDocument (overview, neighbors, search)."""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Iterable, Optional

from ..schemas.graph import GraphDocument, GraphEdge, GraphNode

CLASS_LIKE = {"class", "interface", "object", "enum", "annotation"}
LIFTED_TYPES = {"CALLS", "USES", "EXTENDS", "IMPLEMENTS", "INJECTS", "NAVIGATES_TO", "OVERRIDES"}
LIFECYCLE_ENTRIES = {
    "activity": {"onCreate", "onStart", "onResume", "onNewIntent", "onActivityResult"},
    "application": {"onCreate"},
    "fragment": {"onAttach", "onCreate", "onCreateView", "onViewCreated", "onStart", "onResume"},
    "provider": {"onCreate"},
    "receiver": {"onReceive"},
    "service": {"onCreate", "onStartCommand", "onBind", "onHandleIntent"},
    "worker": {"doWork"},
}


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

    # ---- helpers -----------------------------------------------------------
    def lift(self, node_id: str) -> Optional[str]:
        """Nearest class-level entity for a node (class, or composable function)."""
        if node_id in self._lift_cache:
            return self._lift_cache[node_id]
        cur, res = self.nodes.get(node_id), None
        while cur is not None:
            parent = self.nodes.get(cur.parent_id) if cur.parent_id else None
            python_function = (cur.language == "python"
                               and cur.type in ("function", "constructor")
                               and parent is not None and parent.type == "file")
            if python_function:
                res = cur.id
                break
            if cur.type in CLASS_LIKE or "composable" in cur.roles:
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
    def overview(self, limit: Optional[int] = None) -> dict:
        lifted = self.lifted_edges()

        def is_python_top_level_function(node: GraphNode) -> bool:
            parent = self.nodes.get(node.parent_id) if node.parent_id else None
            return (node.language == "python" and node.type in ("function", "constructor")
                    and parent is not None and parent.type == "file")

        navigated_to = {e.target for e in self.doc.edges
                        if e.type == "NAVIGATES_TO" and e.target}
        entries = []
        for node in self.doc.nodes:
            if node.type not in ("function", "constructor"):
                continue
            parent = self.nodes.get(node.parent_id) if node.parent_id else None
            if parent is not None and parent.id in navigated_to:
                continue
            is_lifecycle = parent is not None and any(
                node.name in LIFECYCLE_ENTRIES.get(role, set()) for role in parent.roles)
            is_java_main = (node.name == "main" and node.language == "java"
                            and "static" in node.modifiers)
            is_python_main = is_python_top_level_function(node) and node.name == "main"
            if is_lifecycle or is_java_main or is_python_main:
                entries.append(node)
        entries.sort(key=lambda n: (n.qualified_name, n.file_path or "", n.start_line or 0))

        fallback = not entries
        if fallback:
            candidates = [
                n for n in self.doc.nodes
                if (n.type in CLASS_LIKE and n.roles)
                or "composable" in n.roles
                or is_python_top_level_function(n)
            ]
            if not candidates:
                candidates = [n for n in self.doc.nodes
                              if n.type in CLASS_LIKE or is_python_top_level_function(n)]
            incoming = {e["target"] for e in lifted}
            entries = [n for n in candidates if n.id not in incoming]
            if not entries:
                degree: dict[str, int] = defaultdict(int)
                for edge in lifted:
                    degree[edge["source"]] += 1
                    degree[edge["target"]] += 1
                entries = sorted(candidates, key=lambda n: (-degree[n.id], n.qualified_name))[:1]
            entries.sort(key=lambda n: (n.qualified_name, n.file_path or "", n.start_line or 0))

        entry_ids = {n.id for n in entries}
        flow_out: dict[str, list[dict]] = defaultdict(list)
        if fallback:
            for edge in lifted:
                if edge["type"] != "USES":
                    flow_out[edge["source"]].append(edge)
        else:
            overrides: dict[str, list[GraphEdge]] = defaultdict(list)
            raw_out: dict[str, list[GraphEdge]] = defaultdict(list)
            lifecycle_by_type: dict[str, list[GraphNode]] = defaultdict(list)
            for edge in self.doc.edges:
                if edge.target and edge.type == "OVERRIDES":
                    overrides[edge.target].append(edge)
                if edge.target and edge.type in ("CALLS", "NAVIGATES_TO"):
                    raw_out[edge.source].append(edge)
            for node in self.doc.nodes:
                parent = self.nodes.get(node.parent_id) if node.parent_id else None
                if (parent and node.type in ("function", "constructor")
                        and any(node.name in LIFECYCLE_ENTRIES.get(role, set())
                                for role in parent.roles)):
                    lifecycle_by_type[parent.id].append(node)
            for nodes in lifecycle_by_type.values():
                nodes.sort(key=lambda n: (n.name, n.qualified_name, n.start_line or 0))

            for source, source_edges in raw_out.items():
                for edge in source_edges:
                    if edge.type == "NAVIGATES_TO":
                        destinations = lifecycle_by_type.get(edge.target, [])
                        if destinations:
                            for destination in destinations:
                                flow_out[source].append({
                                    **edge.model_dump(),
                                    "id": f"overview:{edge.id}:{destination.id}",
                                    "target": destination.id,
                                    "provenance": (f"{edge.provenance}; enters "
                                                   f"{destination.qualified_name}"),
                                })
                            continue
                    flow_out[source].append(edge.model_dump())
                    if edge.type == "CALLS":
                        for override in overrides.get(edge.target, []):
                            implementation = self.nodes[override.source]
                            flow_out[source].append({
                                **edge.model_dump(),
                                "id": f"dispatch:{edge.id}:{override.source}",
                                "target": override.source,
                                "status": "inferred",
                                "provenance": (f"runtime dispatch to override "
                                               f"{implementation.qualified_name}"),
                            })

        levels: dict[str, int] = {}
        queue: deque[str] = deque()
        for node in entries:
            levels[node.id] = 0
            queue.append(node.id)
        while queue:
            source = queue.popleft()
            for edge in flow_out.get(source, []):
                target = edge["target"]
                if target not in levels:
                    levels[target] = levels[source] + 1
                    queue.append(target)

        grouped: dict[int, list[str]] = defaultdict(list)
        for node_id, depth in levels.items():
            grouped[depth].append(node_id)
        for ids in grouped.values():
            ids.sort(key=lambda nid: (self.nodes[nid].qualified_name,
                                      self.nodes[nid].file_path or "",
                                      self.nodes[nid].start_line or 0))

        flow_node_count = len(levels)
        last_flow_level = max(levels.values(), default=-1)
        member_levels: dict[str, list[int]] = defaultdict(list)
        for node in self.doc.nodes:
            if node.type in ("function", "constructor") and node.id in levels:
                owner_id = self.lift(node.id)
                if owner_id and owner_id != node.id:
                    member_levels[owner_id].append(levels[node.id])
        for owner_id, depths in member_levels.items():
            if owner_id in self.nodes and self.nodes[owner_id].type in CLASS_LIKE:
                levels[owner_id] = min(depths)
        for node in self.doc.nodes:
            levels.setdefault(node.id, last_flow_level + 1)
        selected = set(levels)
        if limit is not None:
            selected = set()
            for depth in sorted(grouped):
                remaining = limit - len(selected)
                if remaining <= 0:
                    break
                selected.update(grouped[depth][:remaining])

        # Preserve every extracted relationship, including structural edges and
        # unresolved references; append synthetic runtime-dispatch/navigation flows.
        edge_data = {edge.id: edge.model_dump() for edge in self.doc.edges}
        for source in levels:
            for edge in flow_out.get(source, []):
                if edge["id"] not in edge_data:
                    edge_data[edge["id"]] = edge
        total_candidates = sum(
            1 for n in self.doc.nodes
            if n.type in CLASS_LIKE or "composable" in n.roles or is_python_top_level_function(n))
        node_data = []
        for node_id in selected:
            data = self.node_dict(self.nodes[node_id])
            data["level"] = levels[node_id]
            if node_id in entry_ids:
                data["roles"] = [*data["roles"], "entry_point"]
                data["role_evidence"] = {
                    **data["role_evidence"],
                    "entry_point": "application entry method" if not fallback else "top-level graph root",
                }
            node_data.append(data)
        node_data.sort(key=lambda n: (n["level"], n["qualified_name"], n["id"]))
        all_grouped: dict[int, list[str]] = defaultdict(list)
        for node_id in selected:
            all_grouped[levels[node_id]].append(node_id)
        layers = [
            {"level": depth, "nodes": sorted(ids, key=lambda nid: (
                self.nodes[nid].qualified_name, self.nodes[nid].id))}
            for depth, ids in sorted(all_grouped.items())
        ]
        edges = sorted((edge for edge in edge_data.values()
                        if edge["source"] in selected
                        and (edge["target"] is None or edge["target"] in selected)),
                       key=lambda edge: (levels[edge["source"]],
                                         levels.get(edge["target"], -1),
                                         edge["source"], edge["id"]))
        return {"nodes": node_data, "edges": edges, "levels": layers,
                "total_class_level_nodes": total_candidates,
                "total_reachable_nodes": flow_node_count,
                "total_graph_nodes": len(self.doc.nodes),
                "total_graph_edges": len(self.doc.edges),
                "truncated": len(self.doc.nodes) > len(selected),
                "entry_points": len(entry_ids)}

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

        class_level = node.type in CLASS_LIKE or "composable" in node.roles
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
