"""Symbol resolution on top of syntax facts.

Resolution order for a simple type name (JLS/Kotlin-like, simplified):
lexical nesting -> explicit import / alias -> same package -> wildcard import ->
known built-ins -> unique simple name in repository (inferred). Anything else is
reported as unresolved; nothing is guessed beyond that.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol

from ..schemas.graph import GraphNode
from .model import FuncDecl, ParsedFile, TypeDecl

BUILTINS = {
    "String", "Int", "Long", "Double", "Float", "Boolean", "Byte", "Short", "Char", "Unit",
    "Any", "Nothing", "Object", "Integer", "Void", "Number", "List", "MutableList", "Map",
    "MutableMap", "Set", "MutableSet", "Collection", "Array", "Pair", "Result", "Exception",
    "Throwable", "Runnable", "Iterable", "Sequence", "ArrayList", "HashMap", "Override",
    "Deprecated", "Suppress", "JvmStatic", "JvmField", "JvmOverloads", "Comparable",
    "CharSequence", "StringBuilder", "Class", "Math", "System", "Thread", "Lazy",
    "SuppressWarnings", "FunctionalInterface", "SafeVarargs", "IntArray", "Triple",
    "bool", "bytes", "bytearray", "complex", "dict", "enumerate", "filter", "float",
    "frozenset", "int", "list", "map", "memoryview", "object", "range", "set",
    "slice", "str", "super", "tuple", "type", "zip", "None",
}


@dataclass
class TypeInfo:
    node: GraphNode
    decl: TypeDecl
    pf: ParsedFile
    fqn: str
    outer: Optional["TypeInfo"] = None
    methods: list["FuncInfo"] = field(default_factory=list)
    nested: dict[str, "TypeInfo"] = field(default_factory=dict)
    supers: list["SuperResolution"] = field(default_factory=list)

    def chain(self) -> list["TypeInfo"]:
        out, cur = [], self
        while cur is not None:
            out.append(cur)
            cur = cur.outer
        return out


@dataclass
class FuncInfo:
    node: GraphNode
    decl: FuncDecl
    pf: ParsedFile
    owner: Optional[TypeInfo]


@dataclass
class Resolved:
    status: str  # confirmed | inferred | external | unresolved
    fqn: Optional[str] = None
    info: Optional[TypeInfo] = None
    provenance: str = ""


@dataclass
class SuperResolution:
    name: str
    ref_line: int
    ctor_call: Optional[bool]
    res: Resolved


@dataclass
class FileContext:
    pf: ParsedFile
    explicit: dict[str, str]
    wildcards: list[str]
    enclosing: list[TypeInfo]


class SemanticProvider(Protocol):
    """Extension point: a Kotlin-compiler / JavaParser-backed provider can answer
    resolution queries with real type information. The syntax resolver is the fallback."""

    def resolve_type(self, name: str, ctx: FileContext) -> Optional[Resolved]: ...


class SymbolIndex:
    def __init__(self, provider: SemanticProvider | None = None):
        self.types: dict[str, TypeInfo] = {}
        self.by_simple: dict[str, list[TypeInfo]] = {}
        self.functions: dict[str, list[FuncInfo]] = {}  # top-level, by fqn
        self.functions_by_name: dict[str, list[FuncInfo]] = {}
        self.packages: set[str] = set()
        self.provider = provider
        self.collisions: list[str] = []

    def add_type(self, info: TypeInfo) -> None:
        if info.fqn in self.types:
            self.collisions.append(info.fqn)
            return
        self.types[info.fqn] = info
        self.by_simple.setdefault(info.decl.name, []).append(info)

    def add_function(self, fi: FuncInfo) -> None:
        fqn = f"{fi.pf.package}.{fi.decl.name}" if fi.pf.package else fi.decl.name
        self.functions.setdefault(fqn, []).append(fi)
        self.functions_by_name.setdefault(fi.decl.name, []).append(fi)

    def context(self, pf: ParsedFile, enclosing: list[TypeInfo]) -> FileContext:
        explicit, wild = {}, []
        for imp in pf.imports:
            if imp.static:
                continue
            if imp.wildcard:
                wild.append(imp.path)
            else:
                if imp.module and not imp.alias:
                    binding = imp.path.split(".", 1)[0]
                    explicit[binding] = binding
                else:
                    explicit[imp.alias or imp.path.rsplit(".", 1)[-1]] = imp.path
        return FileContext(pf, explicit, wild, enclosing)

    def resolve_type(self, name: str, ctx: FileContext) -> Resolved:
        if not name:
            return Resolved("unresolved", provenance="empty type name")
        if self.provider is not None:
            r = self.provider.resolve_type(name, ctx)
            if r is not None:
                return r
        segs = name.split(".")
        head, rest = segs[0], segs[1:]
        base = self._resolve_head(head, ctx)
        if base.status == "unresolved" and rest and name in self.types:
            info = self.types[name]
            return Resolved("confirmed", info.fqn, info, "fully-qualified name")
        if not rest or base.status in ("unresolved",):
            return base
        fqn = f"{base.fqn}.{'.'.join(rest)}"
        if fqn in self.types:
            return Resolved(base.status, fqn, self.types[fqn], base.provenance + " + nested")
        if base.status == "external":
            return Resolved("external", fqn, None, base.provenance)
        return Resolved("unresolved", None, None, f"nested type {fqn} not found")

    def _resolve_head(self, head: str, ctx: FileContext) -> Resolved:
        for enc in ctx.enclosing:
            if enc.decl.name == head:
                return Resolved("confirmed", enc.fqn, enc, "lexical scope")
            cand = self.types.get(f"{enc.fqn}.{head}")
            if cand:
                return Resolved("confirmed", cand.fqn, cand, "nested in enclosing type")
        if head in ctx.explicit:
            path = ctx.explicit[head]
            if path in self.types:
                return Resolved("confirmed", path, self.types[path], f"import {path}")
            return Resolved("external", path, None, f"import {path} (outside repository)")
        pkg = ctx.pf.package
        cand = self.types.get(f"{pkg}.{head}" if pkg else head)
        if cand:
            return Resolved("confirmed", cand.fqn, cand, "same package")
        for w in ctx.wildcards:
            cand = self.types.get(f"{w}.{head}")
            if cand:
                return Resolved("confirmed", cand.fqn, cand, f"wildcard import {w}.*")
        if head in BUILTINS:
            return Resolved("external", f"<builtin>.{head}", None, "language/standard library")
        if head in self.types:
            return Resolved("confirmed", head, self.types[head], "fully-qualified name")
        same = self.by_simple.get(head, [])
        if len(same) == 1:
            return Resolved("inferred", same[0].fqn, same[0],
                            "unique simple name in repository (no matching import)")
        if len(same) > 1:
            return Resolved("unresolved", None, None,
                            f"ambiguous simple name '{head}' ({len(same)} declarations, no import)")
        ext_wild = [w for w in ctx.wildcards if w not in self.packages]
        if ext_wild:
            return Resolved("unresolved", None, None,
                            f"'{head}' may come from wildcard import {', '.join(ext_wild[:3])}.*")
        return Resolved("unresolved", None, None, f"no declaration or import found for '{head}'")

    # ---- hierarchy -------------------------------------------------------
    def hierarchy(self, info: TypeInfo) -> list[TypeInfo]:
        seen, order, queue = {info.fqn}, [info], [info]
        while queue:
            cur = queue.pop(0)
            for s in cur.supers:
                t = s.res.info
                if t is not None and t.fqn not in seen:
                    seen.add(t.fqn)
                    order.append(t)
                    queue.append(t)
        return order

    def external_supers(self, info: TypeInfo) -> list[str]:
        out: list[str] = []
        for t in self.hierarchy(info):
            for s in t.supers:
                if s.res.info is None and s.res.status in ("external", "unresolved"):
                    out.append(s.res.fqn or s.name)
        return out

    def find_methods(self, info: TypeInfo, name: str) -> list[FuncInfo]:
        for t in self.hierarchy(info):
            found = [m for m in t.methods if m.decl.name == name and m.decl.kind == "function"]
            if not found:
                comp = [n for n in t.nested.values() if n.decl.is_companion]
                for c in comp:
                    found += [m for m in c.methods if m.decl.name == name]
            if found:
                return found
        return []

    def find_field(self, info: TypeInfo, name: str) -> tuple[Optional[str], Optional[TypeInfo]]:
        for t in self.hierarchy(info):
            for f in t.decl.fields:
                if f.name == name:
                    return f.type_name, t
        return None, None
