"""Builds the code graph (nodes + edges) from parsed files using the symbol index."""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from pathlib import Path
from typing import Optional

from defusedxml import ElementTree as SafeET

from ..schemas.graph import GraphEdge, GraphNode
from .model import CallSite, FuncDecl, ParsedFile, TypeDecl, TypeUse
from .resolver import (FileContext, FuncInfo, Resolved, SemanticProvider, SuperResolution,
                       SymbolIndex, TypeInfo)
from .roles import classify

INJECT_ANNOTATIONS = {"Inject", "AssistedInject"}
FIELD_INJECT_ANNOTATIONS = {"Inject"}
TYPE_NODE_KINDS = {"class", "interface", "object", "enum", "annotation"}
ANDROID_NS = "{http://schemas.android.com/apk/res/android}"
APP_NS = "{http://schemas.android.com/apk/res-auto}"


def _hid(prefix: str, key: str) -> str:
    return f"{prefix}_{hashlib.sha1(key.encode()).hexdigest()[:12]}"


class GraphBuilder:
    def __init__(self, owner: str, repo: str, provider: SemanticProvider | None = None):
        self.repo_name = f"{owner}/{repo}"
        self.index = SymbolIndex(provider)
        self.nodes: dict[str, GraphNode] = {}
        self.edges: dict[tuple, GraphEdge] = {}
        self._changed_nodes: dict[str, GraphNode] = {}
        self._changed_edges: dict[str, GraphEdge] = {}
        self.pkg_nodes: dict[str, GraphNode] = {}
        self.file_nodes: dict[str, GraphNode] = {}
        self.layout_nodes: dict[str, GraphNode] = {}
        self.type_infos: list[TypeInfo] = []
        self.func_infos: list[FuncInfo] = []
        self.counters: Counter = Counter()
        self._all_files: list[ParsedFile] = []
        self.repo_node = self._add_node(GraphNode(
            id=_hid("repo", self.repo_name), type="repository", name=repo, qualified_name=self.repo_name))

    # ---- node/edge helpers ---------------------------------------------
    def _add_node(self, n: GraphNode) -> GraphNode:
        self.nodes[n.id] = n
        self._changed_nodes[n.id] = n
        return n

    def drain_changes(self) -> tuple[list[GraphNode], list[GraphEdge]]:
        nodes = list(self._changed_nodes.values())
        edges = list(self._changed_edges.values())
        self._changed_nodes.clear()
        self._changed_edges.clear()
        return nodes, edges

    def edge(self, etype: str, source: str, target: Optional[str], *, status="confirmed",
             provenance="", file_path=None, line=None, target_name=None) -> None:
        if target is not None and source == target and etype not in ("CALLS",):
            return
        key = (etype, source, target, target_name if target is None else None)
        e = self.edges.get(key)
        if e is None:
            e = GraphEdge(
                id=_hid("e", "|".join(map(str, key))), type=etype, source=source, target=target,
                target_name=target_name, status=status, provenance=provenance,
                file_path=file_path, line=line, lines=[line] if line else [], count=1)
            self.edges[key] = e
        else:
            e.count += 1
            if line and line not in e.lines and len(e.lines) < 25:
                e.lines.append(line)
        self._changed_edges[e.id] = e

    # ---- declaration pass ------------------------------------------------
    def add_parsed_file(self, pf: ParsedFile) -> None:
        self._all_files.append(pf)
        pkg_name = pf.package or "(default)"
        pkg = self.pkg_nodes.get(pkg_name)
        if pkg is None:
            pkg = self._add_node(GraphNode(
                id=_hid("pkg", pkg_name), type="package", name=pkg_name.rsplit(".", 1)[-1],
                qualified_name=pkg_name, package=pkg_name, parent_id=self.repo_node.id))
            self.pkg_nodes[pkg_name] = pkg
            self.index.packages.add(pf.package)
            self.edge("CONTAINS", self.repo_node.id, pkg.id, provenance="package declaration")
        fnode = self._add_node(GraphNode(
            id=_hid("file", pf.path), type="file", name=Path(pf.path).name, qualified_name=pf.path,
            file_path=pf.path, start_line=1, end_line=pf.line_count, language=pf.language,
            package=pkg_name, parent_id=pkg.id))
        self.file_nodes[pf.path] = fnode
        self.edge("CONTAINS", pkg.id, fnode.id, provenance="file in package", file_path=pf.path)
        if pf.package:
            self.edge("DECLARES", fnode.id, pkg.id, provenance="package statement",
                      file_path=pf.path, line=pf.package_line)
        for td in pf.types:
            self._declare_type(td, pf, fnode, None)
        for fd in pf.functions:
            fi = self._declare_func(fd, pf, fnode, None, pf.package)
            self.index.add_function(fi)

    def _declare_type(self, td: TypeDecl, pf: ParsedFile, parent: GraphNode,
                      outer: Optional[TypeInfo]) -> TypeInfo:
        prefix = outer.fqn if outer else pf.package
        fqn = f"{prefix}.{td.name}" if prefix else td.name
        node = self._add_node(GraphNode(
            id=_hid("type", f"{fqn}|{pf.path}"), type=td.kind, name=td.name, qualified_name=fqn,
            file_path=pf.path, start_line=td.start, end_line=td.end, language=pf.language,
            package=pf.package or "(default)", parent_id=parent.id,
            modifiers=sorted(td.modifiers), annotations=td.annotations))
        info = TypeInfo(node, td, pf, fqn, outer)
        self.type_infos.append(info)
        self.index.add_type(info)
        if outer:
            outer.nested[td.name] = info
        self.edge("CONTAINS", parent.id, node.id, provenance="declaration", file_path=pf.path, line=td.start)
        for fd in td.methods:
            info.methods.append(self._declare_func(fd, pf, node, info, fqn))
        for n in td.nested:
            self._declare_type(n, pf, node, info)
        return info

    def _declare_func(self, fd: FuncDecl, pf: ParsedFile, parent: GraphNode,
                      owner: Optional[TypeInfo], prefix: str) -> FuncInfo:
        qn = f"{prefix}.{fd.name}" if prefix else fd.name
        ptypes = ", ".join(f"{p.name}: {p.type_name or '?'}" for p in fd.params)
        sig = f"{fd.name}({ptypes})" + (f": {fd.return_type}" if fd.return_type else "")
        node = self._add_node(GraphNode(
            id=_hid("fn", f"{qn}({ptypes})|{pf.path}:{fd.start}"), type=fd.kind, name=fd.name,
            qualified_name=qn, file_path=pf.path, start_line=fd.start, end_line=fd.end,
            language=pf.language, package=pf.package or "(default)", parent_id=parent.id,
            signature=sig, modifiers=sorted(fd.modifiers), annotations=fd.annotations))
        if "Composable" in fd.annotations:
            node.roles.append("composable")
            node.role_evidence["composable"] = "annotated @Composable"
        self.edge("CONTAINS", parent.id, node.id, provenance="declaration", file_path=pf.path, line=fd.start)
        fi = FuncInfo(node, fd, pf, owner)
        self.func_infos.append(fi)
        return fi

    # ---- resolution pass -------------------------------------------------
    def resolve_all(self) -> None:
        for info in self.type_infos:
            ctx = self.index.context(info.pf, info.chain()[1:])
            for s in info.decl.supers:
                info.supers.append(SuperResolution(s.name, s.line, s.ctor_call,
                                                   self.index.resolve_type(s.name, ctx)))
        self._imports()
        self._hierarchy_edges()
        for info in self.type_infos:
            roles, ev = classify(info, self.index)
            info.node.roles, info.node.role_evidence = roles, ev
        self._overrides()
        for info in self.type_infos:
            self._type_level(info)
        for pf in self._all_files:
            ctx = self.index.context(pf, [])
            for call in pf.calls:
                self._call(self.file_nodes[pf.path], None, None, call, ctx, pf)
        for fi in self.func_infos:
            self._function_level(fi)

    def _imports(self) -> None:
        for pf in self._all_files:
            fnode = self.file_nodes[pf.path]
            for imp in pf.imports:
                target, status, prov = None, "confirmed", f"import {imp.path}"
                name = imp.path
                if imp.wildcard:
                    pkg = self.pkg_nodes.get(imp.path)
                    if pkg:
                        target = pkg.id
                    elif imp.path in self.index.types:
                        target = self.index.types[imp.path].node.id
                else:
                    cand = imp.path
                    if imp.static and cand not in self.index.types:
                        cand = cand.rsplit(".", 1)[0]
                    if cand in self.index.types:
                        target = self.index.types[cand].node.id
                    elif cand in self.index.functions:
                        target = self.index.functions[cand][0].node.id
                    elif cand in self.pkg_nodes:
                        target = self.pkg_nodes[cand].id
                if target is None:
                    status, prov = "external", f"import {imp.path} (outside repository)"
                self.edge("IMPORTS", fnode.id, target, status=status, provenance=prov,
                          file_path=pf.path, line=imp.line, target_name=None if target else name)

    def _hierarchy_edges(self) -> None:
        for info in self.type_infos:
            for s in info.supers:
                r = s.res
                if info.decl.kind == "interface":
                    etype = "EXTENDS"
                elif r.info is not None:
                    etype = "IMPLEMENTS" if r.info.decl.kind == "interface" else "EXTENDS"
                else:
                    etype = "EXTENDS" if s.ctor_call else "IMPLEMENTS"
                    if info.pf.language == "kotlin" and not s.ctor_call:
                        etype = "IMPLEMENTS"
                if r.info is not None:
                    self.edge(etype, info.node.id, r.info.node.id, status=r.status,
                              provenance=f"supertype resolved via {r.provenance}",
                              file_path=info.pf.path, line=s.ref_line)
                else:
                    st = "external" if r.status == "external" else "unresolved"
                    self.edge(etype, info.node.id, None, status=st, target_name=r.fqn or s.name,
                              provenance=r.provenance, file_path=info.pf.path, line=s.ref_line)

    def _overrides(self) -> None:
        for info in self.type_infos:
            hier = self.index.hierarchy(info)[1:]
            for m in info.methods:
                if m.decl.kind != "function" or not hier:
                    continue
                marked = "override" in m.decl.modifiers or "Override" in m.decl.annotations
                for anc in hier:
                    cands = [x for x in anc.methods if x.decl.name == m.decl.name
                             and x.decl.kind == "function" and len(x.decl.params) == len(m.decl.params)]
                    if cands:
                        for c in cands:
                            self.edge("OVERRIDES", m.node.id, c.node.id,
                                      status="confirmed" if marked else "inferred",
                                      provenance=("override marker + same name/arity in supertype"
                                                  if marked else "same name/arity in supertype; no override marker"),
                                      file_path=m.pf.path, line=m.decl.start)
                        break

    # ---- uses / injects / calls --------------------------------------------
    def _use_edges(self, source: GraphNode, uses: list[TypeUse], ctx: FileContext,
                   pf: ParsedFile, owner: Optional[TypeInfo]) -> None:
        for u in uses:
            r = self.index.resolve_type(u.name, ctx)
            if r.info is None:
                if r.status == "unresolved":
                    self.counters["unresolved_type_refs"] += 1
                self._layout_binding(source, u, pf)
                continue
            if owner is not None and r.info is owner:
                continue
            self.edge("USES", source.id, r.info.node.id, status=r.status,
                      provenance=f"{u.context} reference via {r.provenance}",
                      file_path=pf.path, line=u.line)

    def _layout_binding(self, source: GraphNode, u: TypeUse, pf: ParsedFile) -> None:
        simple = u.name.rsplit(".", 1)[-1]
        if simple.endswith("Binding") and len(simple) > 7:
            snake = re.sub(r"(?<!^)(?=[A-Z])", "_", simple[:-7]).lower()
            lay = self.layout_nodes.get(snake)
            if lay:
                self.edge("USES", source.id, lay.id, status="inferred",
                          provenance="view-binding class name maps to layout file",
                          file_path=pf.path, line=u.line)

    def _res_edges(self, source: GraphNode, refs, pf: ParsedFile) -> None:
        for kind, name, ln in refs:
            if kind == "layout" and name in self.layout_nodes:
                self.edge("USES", source.id, self.layout_nodes[name].id, status="confirmed",
                          provenance=f"R.layout.{name}", file_path=pf.path, line=ln)

    def _type_level(self, info: TypeInfo) -> None:
        pf = info.pf
        ctx = self.index.context(pf, info.chain())
        self._use_edges(info.node, info.decl.type_uses, ctx, pf, info)
        self._res_edges(info.node, info.decl.resource_refs, pf)
        for f in info.decl.fields:
            if set(f.annotations) & FIELD_INJECT_ANNOTATIONS and f.type_name:
                self._inject(info.node, f.type_name, ctx, pf, f.line, f"@Inject field `{f.name}`")
        for m in info.methods:
            if m.decl.kind == "constructor" and (m.decl.injected_params or
                                                 set(m.decl.annotations) & INJECT_ANNOTATIONS):
                for p in m.decl.params:
                    if p.type_name:
                        self._inject(info.node, p.type_name, ctx, pf, m.decl.start,
                                     f"@Inject constructor param `{p.name}`")
        for c in info.decl.calls:
            self._call(info.node, info, None, c, ctx, pf)
        for target, ln in info.decl.intents:
            self._navigate(info.node, target, ctx, pf, ln)

    def _inject(self, source: GraphNode, tname: str, ctx: FileContext, pf: ParsedFile,
                ln: int, why: str) -> None:
        r = self.index.resolve_type(tname, ctx)
        if r.info is not None:
            self.edge("INJECTS", source.id, r.info.node.id, status=r.status,
                      provenance=f"{why}; type via {r.provenance}", file_path=pf.path, line=ln)
        elif r.status == "external":
            self.edge("INJECTS", source.id, None, status="external", target_name=r.fqn,
                      provenance=why, file_path=pf.path, line=ln)
        else:
            self.edge("INJECTS", source.id, None, status="unresolved", target_name=tname,
                      provenance=f"{why}; {r.provenance}", file_path=pf.path, line=ln)

    def _navigate(self, source: GraphNode, target: str, ctx: FileContext, pf: ParsedFile, ln: int) -> None:
        r = self.index.resolve_type(target, ctx)
        if r.info is not None:
            self.edge("NAVIGATES_TO", source.id, r.info.node.id, status=r.status,
                      provenance=f"explicit Intent to {target}::class via {r.provenance}",
                      file_path=pf.path, line=ln)

    def _function_level(self, fi: FuncInfo) -> None:
        pf, owner = fi.pf, fi.owner
        ctx = self.index.context(pf, owner.chain() if owner else [])
        self._use_edges(fi.node, fi.decl.type_uses, ctx, pf, owner)
        self._res_edges(fi.node, fi.decl.resource_refs, pf)
        for c in fi.decl.calls:
            self._call(fi.node, owner, fi, c, ctx, pf)
        for target, ln in fi.decl.intents:
            self._navigate(fi.node, target, ctx, pf, ln)

    # ---- call resolution ---------------------------------------------------
    def _call(self, source: GraphNode, owner: Optional[TypeInfo], fi: Optional[FuncInfo],
              c: CallSite, ctx: FileContext, pf: ParsedFile) -> None:
        def emit_targets(targets: list[FuncInfo], status: str, why: str) -> None:
            for t in targets[:6]:
                self.edge("CALLS", source.id, t.node.id, status=status, provenance=why,
                          file_path=pf.path, line=c.line)

        def unresolved(why: str) -> None:
            label = f"{c.receiver + '.' if c.receiver and c.receiver != '<complex>' else ''}{c.name}"
            self.counters["unresolved_calls"] += 1
            self.edge("CALLS", source.id, None, status="unresolved", target_name=label,
                      provenance=why, file_path=pf.path, line=c.line)

        def external(fqn: str, why: str) -> None:
            self.edge("CALLS", source.id, None, status="external", target_name=fqn,
                      provenance=why, file_path=pf.path, line=c.line)

        def pick(cands: list[FuncInfo]) -> tuple[list[FuncInfo], str]:
            exact = [m for m in cands if len(m.decl.params) == c.argc]
            if len(exact) == 1:
                return exact, "confirmed"
            if len(exact) > 1:
                return exact, "inferred"
            loose = [m for m in cands if len(m.decl.params) >= c.argc]
            if len(loose) == 1:
                return loose, "inferred"
            return [], "unresolved"

        def via_type(r: Resolved, label: str) -> None:
            if r.info is not None:
                cands = self.index.find_methods(r.info, c.name)
                chosen, st = pick(cands)
                if chosen:
                    iface = any(m.owner and m.owner.decl.kind == "interface" for m in chosen)
                    why = f"{label} -> {r.info.fqn} ({r.provenance})"
                    if iface:
                        why += "; declared on interface, runtime dispatch may reach implementations"
                    if r.status == "inferred" and st == "confirmed":
                        st = "inferred"
                    emit_targets(chosen, st, why)
                    return
                ext = self.index.external_supers(r.info)
                ext_fn = [f for f in self.index.functions_by_name.get(c.name, []) if f.decl.receiver_type]
                if len(ext_fn) == 1:
                    emit_targets(ext_fn, "inferred", "extension function matched by name only")
                    return
                unresolved(f"method not declared in {r.info.fqn}"
                           + (f"; may be inherited from {ext[0]}" if ext else ""))
            elif r.status == "external":
                external(f"{r.fqn}.{c.name}", f"{label}: receiver type outside repository")
            else:
                unresolved(f"{label}: receiver type unresolved ({r.provenance})")

        # constructor invocation
        if c.receiver is None and (c.kind == "new" or c.name[:1].isupper()):
            r = self.index.resolve_type(c.name, ctx)
            if r.info is not None:
                ctors = [m for m in r.info.methods if m.decl.kind == "constructor"]
                chosen, st = pick(ctors)
                if chosen:
                    emit_targets(chosen, st if r.status == "confirmed" else "inferred",
                                 f"constructor of {r.info.fqn} ({r.provenance})")
                self.edge("USES", source.id, r.info.node.id, status=r.status,
                          provenance=f"instantiation via {r.provenance}", file_path=pf.path, line=c.line)
                return
            if r.status == "external":
                external(f"{r.fqn}.<init>", "constructor of type outside repository")
                return
            if c.kind == "new":
                unresolved(f"constructor of unresolved type ({r.provenance})")
                return

        locals_ = fi.decl.locals if fi else {}
        params = {p.name: p.type_name for p in fi.decl.params} if fi else {}

        def var_type(name: str) -> tuple[Optional[str], FileContext]:
            if name in locals_:
                return locals_[name], ctx
            if params.get(name):
                return params[name], ctx
            if owner is not None:
                for scope in owner.chain():
                    tn, declarer = self.index.find_field(scope, name)
                    if tn:
                        return tn, self.index.context(declarer.pf, declarer.chain())
            return None, ctx

        recv = c.receiver
        if recv == "<complex>":
            unresolved("receiver is a call chain or complex expression; no static type available")
            return
        if recv == "super":
            if owner is None:
                unresolved("super call outside a class")
                return
            for s in owner.supers:
                if s.res.info is not None:
                    cands = self.index.find_methods(s.res.info, c.name)
                    chosen, st = pick(cands)
                    if chosen:
                        emit_targets(chosen, st, f"super call via {s.res.info.fqn}")
                        return
            ext = self.index.external_supers(owner)
            if ext:
                external(f"{ext[0]}.{c.name}", "super call to supertype outside repository")
            else:
                unresolved("super method not found")
            return
        if recv is None or recv == "this":
            if owner is not None:
                for scope in owner.chain():
                    cands = self.index.find_methods(scope, c.name)
                    chosen, st = pick(cands)
                    if chosen:
                        emit_targets(chosen, st, f"method of {scope.fqn} (or its supertypes)")
                        return
            if recv is None:
                pkg = pf.package
                fn_cands = list(self.index.functions.get(f"{pkg}.{c.name}" if pkg else c.name, []))
                for imp in pf.imports:
                    imported_name = imp.alias or imp.path.rsplit(".", 1)[-1]
                    if not imp.wildcard and not imp.module and imported_name == c.name:
                        fn_cands += self.index.functions.get(imp.path, [])
                    elif imp.wildcard:
                        fn_cands += self.index.functions.get(f"{imp.path}.{c.name}", [])
                chosen, st = pick(fn_cands)
                if chosen:
                    emit_targets(chosen, st, "top-level function (same package or import)")
                    return
                for imp in pf.imports:
                    imported_name = imp.alias or imp.path.rsplit(".", 1)[-1]
                    if imported_name == c.name and not imp.module and not imp.wildcard \
                            and imp.path not in self.index.types:
                        external(imp.path, f"imported function {imp.path} (outside repository)")
                        return
            ext = self.index.external_supers(owner) if owner else []
            unresolved("no matching declaration in repository"
                       + (f"; may be inherited from {ext[0]}" if ext else "; may be a framework/library call"))
            return
        # explicit receiver
        if pf.language == "python":
            for imp in pf.imports:
                imported_name = imp.alias or imp.path.rsplit(".", 1)[-1]
                if imp.module and (recv == imp.path or recv == imported_name):
                    module = imp.path
                elif not imp.module and imp.path in self.pkg_nodes and recv == imported_name:
                    module = imp.path
                else:
                    continue
                imported_type = self.index.resolve_type(
                    f"{module}.{c.name}", self.index.context(pf, owner.chain() if owner else []))
                if imported_type.info is not None and c.name[:1].isupper():
                    constructors = [m for m in imported_type.info.methods
                                    if m.decl.kind == "constructor"]
                    chosen, st = pick(constructors)
                    if chosen:
                        emit_targets(chosen, st,
                                     f"constructor of {imported_type.info.fqn} via import {imp.path}")
                    self.edge("USES", source.id, imported_type.info.node.id,
                              status=imported_type.status,
                              provenance=f"instantiation via imported module {imp.path}",
                              file_path=pf.path, line=c.line)
                    return
                cands = self.index.functions.get(f"{module}.{c.name}", [])
                chosen, st = pick(cands)
                if chosen:
                    emit_targets(chosen, st, f"module function via import {imp.path}")
                    return
                unresolved(f"function `{c.name}` not declared in imported module {module}")
                return
        parts = recv.split(".")
        if parts[0] == "this" and len(parts) == 2:
            tn, fctx = var_type(parts[1])
            label = f"field `{parts[1]}`"
        elif len(parts) == 1:
            tn, fctx = var_type(parts[0])
            label = f"variable `{parts[0]}`"
        else:
            tn, fctx = None, ctx
            label = ""
        if tn:
            via_type(self.index.resolve_type(tn, fctx), label)
            return
        # static / object / companion access
        r = self.index.resolve_type(recv, ctx)
        if r.status != "unresolved":
            via_type(r, f"static/object access `{recv}`")
            return
        unresolved(f"receiver `{recv}` has no known declared type")

    # ---- XML resources -----------------------------------------------------
    def add_layout(self, rel: str) -> None:
        stem = Path(rel).stem
        node = self._add_node(GraphNode(
            id=_hid("layout", rel), type="layout", name=stem, qualified_name=f"layout/{stem}",
            file_path=rel, start_line=1, language="xml", parent_id=self.repo_node.id))
        self.layout_nodes.setdefault(stem, node)
        self.edge("CONTAINS", self.repo_node.id, node.id, provenance="layout resource", file_path=rel)

    def add_navigation(self, rel: str, path: Path) -> None:
        try:
            root = SafeET.parse(str(path)).getroot()
        except Exception:
            self.counters["xml_parse_errors"] += 1
            return
        ids: dict[str, Optional[TypeInfo]] = {}

        def attr(el, ns, name):
            return el.attrib.get(ns + name)

        def find_class(cls: str) -> Optional[TypeInfo]:
            if not cls:
                return None
            if cls in self.index.types:
                return self.index.types[cls]
            simple = cls.lstrip(".").rsplit(".", 1)[-1]
            cands = self.index.by_simple.get(simple, [])
            return cands[0] if len(cands) == 1 else None

        for el in root.iter():
            did = attr(el, ANDROID_NS, "id")
            if did:
                ids[did.split("/")[-1]] = find_class(attr(el, ANDROID_NS, "name") or "")
        for el in root.iter():
            did = attr(el, ANDROID_NS, "id")
            src = ids.get(did.split("/")[-1]) if did else None
            if not src:
                continue
            for act in el:
                dest = attr(act, APP_NS, "destination")
                if act.tag.endswith("action") and dest:
                    tgt = ids.get(dest.split("/")[-1])
                    if tgt:
                        self.edge("NAVIGATES_TO", src.node.id, tgt.node.id, status="confirmed",
                                  provenance=f"navigation graph action ({rel})", file_path=rel)

    def finish(self) -> tuple[list[GraphNode], list[GraphEdge], dict]:
        nodes = list(self.nodes.values())
        edges = list(self.edges.values())
        stats = {
            "nodes": len(nodes), "edges": len(edges),
            "node_types": dict(Counter(n.type for n in nodes)),
            "edge_types": dict(Counter(e.type for e in edges)),
            "resolution": dict(Counter(e.status for e in edges)),
            "roles": dict(Counter(r for n in nodes for r in n.roles)),
            "unresolved_calls": self.counters["unresolved_calls"],
            "unresolved_type_references": self.counters["unresolved_type_refs"],
            "duplicate_fqn_declarations": len(self.index.collisions),
        }
        return nodes, edges, stats
