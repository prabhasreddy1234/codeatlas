from __future__ import annotations

import re

import tree_sitter_java
from tree_sitter import Language, Node, Parser

from .common import end_line, line, resource_refs, text, walk
from .model import (CallSite, FieldDecl, FuncDecl, ImportDecl, Param, ParsedFile,
                    SuperRef, TypeDecl, TypeUse)

_LANG = Language(tree_sitter_java.language())
_SIMPLE_RECV = re.compile(r"^[A-Za-z_][\w]*(\.[A-Za-z_][\w]*)*$")
TYPE_NODES = {
    "class_declaration": "class", "interface_declaration": "interface",
    "enum_declaration": "enum", "annotation_type_declaration": "annotation",
    "record_declaration": "class",
}


def _parser() -> Parser:
    return Parser(_LANG)


def type_names(node: Node | None) -> list[str]:
    """Dotted type names appearing in a type node (generics' arguments included)."""
    out: list[str] = []
    if node is None:
        return out
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type == "type_identifier":
            out.append(text(n))
        elif n.type == "scoped_type_identifier":
            out.append(text(n))
        else:
            stack.extend(reversed(n.children))
    return out


def _annotations(mods: Node | None) -> tuple[list[str], set[str]]:
    anns: list[str] = []
    flags: set[str] = set()
    if mods is None:
        return anns, flags
    for c in mods.children:
        if c.type in ("marker_annotation", "annotation"):
            nm = c.child_by_field_name("name")
            anns.append(text(nm).lstrip("@"))
        else:
            flags.add(text(c))
    return anns, flags


def _receiver(obj: Node | None) -> str | None:
    if obj is None:
        return None
    t = text(obj)
    if obj.type == "this":
        return "this"
    if obj.type == "super":
        return "super"
    if obj.type in ("identifier", "field_access", "scoped_identifier") and _SIMPLE_RECV.match(t):
        return t
    return "<complex>"


def _scan_body(body: Node, fn_like) -> None:
    """Collect calls, instantiations, locals, intents from a body into fn_like."""
    for n in walk(body):
        if n.type == "method_invocation":
            nm = n.child_by_field_name("name")
            args = n.child_by_field_name("arguments")
            fn_like.calls.append(CallSite(text(nm), _receiver(n.child_by_field_name("object")),
                                          line(n), args.named_child_count if args else 0))
        elif n.type == "object_creation_expression":
            tnode = n.child_by_field_name("type")
            names = type_names(tnode)
            args = n.child_by_field_name("arguments")
            if names:
                fn_like.calls.append(CallSite(names[0], None, line(n),
                                              args.named_child_count if args else 0, "new"))
                fn_like.type_uses.append(TypeUse(names[0], line(n), "instantiation"))
                if names[0].split(".")[-1] == "Intent" and args is not None:
                    for a in walk(args):
                        if a.type == "class_literal":
                            tn = type_names(a)
                            if tn:
                                fn_like.intents.append((tn[0], line(n)))
        elif n.type == "local_variable_declaration" and hasattr(fn_like, "locals"):
            tnode = n.child_by_field_name("type")
            tn = type_names(tnode)
            for d in n.children:
                if d.type == "variable_declarator":
                    nm = text(d.child_by_field_name("name"))
                    if tn and text(tnode) != "var":
                        fn_like.locals[nm] = tn[0]
                    else:
                        val = d.child_by_field_name("value")
                        if val is not None and val.type == "object_creation_expression":
                            vt = type_names(val.child_by_field_name("type"))
                            if vt:
                                fn_like.locals[nm] = vt[0]
                    for t in tn:
                        fn_like.type_uses.append(TypeUse(t, line(n)))
        elif n.type in ("catch_formal_parameter", "instanceof_expression", "cast_expression"):
            for t in type_names(n):
                fn_like.type_uses.append(TypeUse(t, line(n)))
        elif n.type in ("marker_annotation", "annotation"):
            nm = text(n.child_by_field_name("name"))
            fn_like.type_uses.append(TypeUse(nm, line(n), "annotation"))
    fn_like.resource_refs.extend(resource_refs(body))


def _params(node: Node | None) -> list[Param]:
    out = []
    if node is None:
        return out
    for p in node.children:
        if p.type in ("formal_parameter", "spread_parameter"):
            tn = type_names(p.child_by_field_name("type") or p)
            nm = p.child_by_field_name("name")
            out.append(Param(text(nm), tn[0] if tn else None))
    return out


def _func(n: Node, kind: str) -> FuncDecl:
    mods = next((c for c in n.children if c.type == "modifiers"), None)
    anns, flags = _annotations(mods)
    nm = n.child_by_field_name("name")
    params = _params(n.child_by_field_name("parameters"))
    ret = None
    if kind == "function":
        rn = type_names(n.child_by_field_name("type"))
        ret = rn[0] if rn else None
    fd = FuncDecl(text(nm), kind, line(n), end_line(n), params, ret, anns, flags)
    for p in params:
        if p.type_name:
            fd.type_uses.append(TypeUse(p.type_name, line(n)))
    if ret:
        fd.type_uses.append(TypeUse(ret, line(n)))
    for a in anns:
        fd.type_uses.append(TypeUse(a, line(n), "annotation"))
    body = n.child_by_field_name("body")
    if body is not None:
        _scan_body(body, fd)
    fd.injected_params = "Inject" in anns
    return fd


def _type(n: Node) -> TypeDecl:
    kind = TYPE_NODES[n.type]
    mods = next((c for c in n.children if c.type == "modifiers"), None)
    anns, flags = _annotations(mods)
    td = TypeDecl(kind, text(n.child_by_field_name("name")), line(n), end_line(n), anns, flags)
    for a in anns:
        td.type_uses.append(TypeUse(a, line(n), "annotation"))
    for c in n.children:
        if c.type == "superclass":
            for t in type_names(c)[:1]:
                td.supers.append(SuperRef(t, line(c), True))
        elif c.type in ("super_interfaces", "extends_interfaces"):
            tl = next((x for x in c.children if x.type == "type_list"), c)
            for t in tl.named_children:
                names = type_names(t) if t.type != "type_identifier" else [text(t)]
                if names:
                    td.supers.append(SuperRef(names[0], line(c), False))
    if n.type == "record_declaration":
        ps = _params(n.child_by_field_name("parameters"))
        for p in ps:
            td.fields.append(FieldDecl(p.name, p.type_name, line(n)))
    body = n.child_by_field_name("body")
    if body is not None:
        members = []
        for c in body.children:
            if c.type == "enum_body_declarations":
                members.extend(c.children)
            else:
                members.append(c)
        for m in members:
            if m.type == "method_declaration":
                td.methods.append(_func(m, "function"))
            elif m.type == "constructor_declaration":
                td.methods.append(_func(m, "constructor"))
            elif m.type == "field_declaration":
                fm = next((c for c in m.children if c.type == "modifiers"), None)
                anns2, _ = _annotations(fm)
                tn = type_names(m.child_by_field_name("type"))
                for d in m.children:
                    if d.type == "variable_declarator":
                        td.fields.append(FieldDecl(text(d.child_by_field_name("name")),
                                                   tn[0] if tn else None, line(m), anns2))
                        val = d.child_by_field_name("value")
                        if val is not None:
                            _scan_body(val, td)
                for t in tn:
                    td.type_uses.append(TypeUse(t, line(m)))
                for a in anns2:
                    td.type_uses.append(TypeUse(a, line(m), "annotation"))
            elif m.type in TYPE_NODES:
                td.nested.append(_type(m))
            elif m.type in ("static_initializer", "block"):
                _scan_body(m, td)
    return td


class JavaFileBuilder:
    """Collect Java syntax facts from a parsed source tree."""

    def __init__(self, path: str, source: bytes) -> None:
        self.path = path
        self.source = source
        self.file = ParsedFile(
            path=path,
            language="java",
            line_count=source.count(b"\n") + 1,
        )

    def build(self) -> ParsedFile:
        root = _parser().parse(self.source).root_node
        self.file.has_errors = root.has_error
        self._collect_top_level_members(root)
        return self.file

    def _collect_top_level_members(self, root: Node) -> None:
        for child in root.children:
            if child.type == "package_declaration":
                self._collect_package(child)
            elif child.type == "import_declaration":
                self._collect_import(child)
            elif child.type in TYPE_NODES:
                self.file.types.append(_type(child))

    def _collect_package(self, node: Node) -> None:
        name_node = next((child for child in node.children if child.type in ("scoped_identifier", "identifier")), None)
        self.file.package, self.file.package_line = text(name_node), line(node)

    def _collect_import(self, node: Node) -> None:
        name_node = next((child for child in node.children if child.type in ("scoped_identifier", "identifier")), None)
        self.file.imports.append(
            ImportDecl(
                text(name_node),
                any(child.type == "asterisk" for child in node.children),
                None,
                any(child.type == "static" for child in node.children),
                line(node),
            )
        )


def parse_java(path: str, source: bytes) -> ParsedFile:
    return JavaFileBuilder(path, source).build()
