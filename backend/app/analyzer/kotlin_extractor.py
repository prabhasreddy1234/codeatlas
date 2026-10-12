from __future__ import annotations

import re

import tree_sitter_kotlin
from tree_sitter import Language, Node, Parser

from .common import end_line, line, resource_refs, text, walk
from .model import (CallSite, FieldDecl, FuncDecl, ImportDecl, Param, ParsedFile,
                    SuperRef, TypeDecl, TypeUse)

_LANG = Language(tree_sitter_kotlin.language())
_SIMPLE_RECV = re.compile(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)*$")
_CLASS_LIT = re.compile(r"^([A-Za-z_][\w.]*)::class")
_TYPE_WRAPPERS = ("user_type", "nullable_type", "function_type", "parenthesized_type")


def _parser() -> Parser:
    return Parser(_LANG)


def _user_type_name(n: Node) -> str:
    return ".".join(text(c) for c in n.children if c.type == "identifier")


def type_names(node: Node | None) -> list[str]:
    out: list[str] = []
    if node is None:
        return out
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type == "user_type":
            name = _user_type_name(n)
            if name:
                out.append(name)
            for c in reversed(n.children):
                if c.type == "type_arguments":
                    stack.append(c)
        else:
            stack.extend(reversed(n.children))
    return out


def _annotations(mods: Node | None) -> tuple[list[str], set[str]]:
    anns: list[str] = []
    flags: set[str] = set()
    if mods is None:
        return anns, flags
    for c in mods.children:
        if c.type == "annotation":
            ut = next((x for x in walk(c) if x.type == "user_type"), None)
            if ut is not None:
                anns.append(_user_type_name(ut))
        else:
            flags.add(text(c))
    return anns, flags


def _direct(n: Node, kind: str) -> Node | None:
    return next((c for c in n.children if c.type == kind), None)


def _ident(n: Node) -> str:
    c = n.child_by_field_name("name") or _direct(n, "identifier")
    return text(c)


def _receiver(expr: Node) -> str | None:
    t = text(expr)
    if expr.type == "this_expression":
        return "this"
    if expr.type == "super_expression":
        return "super"
    if expr.type in ("identifier", "navigation_expression") and _SIMPLE_RECV.match(t):
        return t
    if expr.type == "navigation_expression" and t.startswith("this.") and _SIMPLE_RECV.match(t[5:]):
        return t
    return "<complex>"


def _argc(call: Node) -> int:
    va = _direct(call, "value_arguments")
    n = va.named_child_count if va is not None else 0
    if _direct(call, "annotated_lambda") is not None:
        n += 1
    return n


def _scan_body(body: Node, fn_like) -> None:
    for n in walk(body):
        if n.type == "call_expression" and n.child_count:
            callee = n.children[0]
            if callee.type == "identifier":
                name = text(callee)
                fn_like.calls.append(CallSite(name, None, line(n), _argc(n)))
                if name == "Intent":
                    for a in walk(_direct(n, "value_arguments") or n):
                        m = _CLASS_LIT.match(text(a)) if a.type == "navigation_expression" else None
                        if m:
                            fn_like.intents.append((m.group(1), line(n)))
                            break
            elif callee.type == "navigation_expression" and callee.child_count >= 3:
                name = text(callee.children[-1])
                recv = _receiver(callee.children[0])
                fn_like.calls.append(CallSite(name, recv, line(n), _argc(n)))
        elif n.type == "property_declaration" and hasattr(fn_like, "locals"):
            vd = _direct(n, "variable_declaration")
            if vd is not None:
                nm = _ident(vd)
                tn = type_names(vd)
                if tn:
                    fn_like.locals[nm] = tn[0]
                    fn_like.type_uses.append(TypeUse(tn[0], line(n)))
                else:
                    init = next((c for c in n.children if c.type == "call_expression"), None)
                    if init is not None and init.children[0].type == "identifier":
                        callee = text(init.children[0])
                        if callee[:1].isupper():
                            fn_like.locals[nm] = callee
        elif n.type == "navigation_expression":
            m = _CLASS_LIT.match(text(n))
            if m:
                fn_like.type_uses.append(TypeUse(m.group(1), line(n), "class-literal"))
        elif n.type in ("as_expression", "is_expression"):
            for t in type_names(n):
                fn_like.type_uses.append(TypeUse(t, line(n)))
        elif n.type == "annotation":
            for t in type_names(n)[:1]:
                fn_like.type_uses.append(TypeUse(t, line(n), "annotation"))
    fn_like.resource_refs.extend(resource_refs(body))


def _params(node: Node | None) -> list[Param]:
    out: list[Param] = []
    if node is None:
        return out
    for p in node.children:
        if p.type in ("parameter", "class_parameter"):
            tn = type_names(p)
            out.append(Param(_ident(p), tn[0] if tn else None))
    return out


def _function(n: Node) -> FuncDecl:
    anns, flags = _annotations(_direct(n, "modifiers"))
    ident = _direct(n, "identifier")
    recv = None
    for c in n.children:
        if c is ident:
            break
        if c.type in ("user_type", "nullable_type"):
            tn = type_names(c)
            recv = tn[0] if tn else None
    params = _params(_direct(n, "function_value_parameters"))
    ret = None
    seen_params = False
    for c in n.children:
        if c.type == "function_value_parameters":
            seen_params = True
        elif seen_params and c.type in ("user_type", "nullable_type"):
            tn = type_names(c)
            ret = tn[0] if tn else None
            break
    fd = FuncDecl(text(ident), "function", line(n), end_line(n), params, ret, anns, flags,
                  receiver_type=recv)
    for p in params:
        if p.type_name:
            fd.type_uses.append(TypeUse(p.type_name, line(n)))
    if ret:
        fd.type_uses.append(TypeUse(ret, line(n)))
    if recv:
        fd.type_uses.append(TypeUse(recv, line(n)))
    for a in anns:
        fd.type_uses.append(TypeUse(a, line(n), "annotation"))
    for c in n.children:
        if c.type in ("function_body", "function_value_parameters"):
            _scan_body(c, fd)
    return fd


def _secondary_ctor(n: Node, owner: str) -> FuncDecl:
    anns, flags = _annotations(_direct(n, "modifiers"))
    params = _params(_direct(n, "function_value_parameters"))
    fd = FuncDecl(owner, "constructor", line(n), end_line(n), params, None, anns, flags)
    fd.injected_params = "Inject" in anns
    for p in params:
        if p.type_name:
            fd.type_uses.append(TypeUse(p.type_name, line(n)))
    _scan_body(n, fd)
    return fd


def _class(n: Node) -> TypeDecl:
    anns, flags = _annotations(_direct(n, "modifiers"))
    is_obj = n.type == "object_declaration"
    kind = "object" if is_obj else "class"
    if _direct(n, "interface") is not None:
        kind = "interface"
    elif "enum" in flags:
        kind = "enum"
    elif "annotation" in flags:
        kind = "annotation"
    td = TypeDecl(kind, _ident(n), line(n), end_line(n), anns, flags)
    for a in anns:
        td.type_uses.append(TypeUse(a, line(n), "annotation"))
    ds = _direct(n, "delegation_specifiers")
    if ds is not None:
        for spec in ds.children:
            if spec.type != "delegation_specifier":
                continue
            ctor = _direct(spec, "constructor_invocation") is not None
            for t in type_names(spec)[:1]:
                td.supers.append(SuperRef(t, line(spec), ctor))
    pc = _direct(n, "primary_constructor")
    if pc is not None:
        c_anns, c_flags = _annotations(_direct(pc, "modifiers"))
        params = _params(_direct(pc, "class_parameters"))
        fd = FuncDecl(td.name, "constructor", line(pc), end_line(pc), params, None, c_anns, c_flags)
        fd.injected_params = "Inject" in c_anns or "Inject" in anns
        for p in params:
            if p.type_name:
                fd.type_uses.append(TypeUse(p.type_name, line(pc)))
        td.methods.append(fd)
        cp = _direct(pc, "class_parameters")
        for p in (cp.children if cp else []):
            if p.type == "class_parameter":
                tn = type_names(p)
                p_anns, _ = _annotations(_direct(p, "modifiers"))
                if _direct(p, "val") is not None or _direct(p, "var") is not None:
                    td.fields.append(FieldDecl(_ident(p), tn[0] if tn else None, line(p), p_anns))
                for t in tn:
                    td.type_uses.append(TypeUse(t, line(p)))
    body = _direct(n, "class_body") or _direct(n, "enum_class_body")
    if body is not None:
        for m in body.children:
            if m.type == "function_declaration":
                td.methods.append(_function(m))
            elif m.type == "secondary_constructor":
                td.methods.append(_secondary_ctor(m, td.name))
            elif m.type == "property_declaration":
                vd = _direct(m, "variable_declaration")
                if vd is not None:
                    tn = type_names(vd)
                    p_anns, _ = _annotations(_direct(m, "modifiers"))
                    td.fields.append(FieldDecl(_ident(vd), tn[0] if tn else None, line(m), p_anns))
                    for t in tn:
                        td.type_uses.append(TypeUse(t, line(m)))
                    for a in p_anns:
                        td.type_uses.append(TypeUse(a, line(m), "annotation"))
                    if not tn:
                        init = next((c for c in m.children if c.type == "call_expression"), None)
                        if init is not None and init.children[0].type == "identifier":
                            cn = text(init.children[0])
                            if cn[:1].isupper():
                                td.fields[-1].type_name = cn
                _scan_body(m, td)
            elif m.type == "anonymous_initializer":
                _scan_body(m, td)
            elif m.type in ("class_declaration", "object_declaration"):
                td.nested.append(_class(m))
            elif m.type == "companion_object":
                comp = _class(m)
                comp.is_companion = True
                comp.kind = "object"
                comp.name = comp.name or "Companion"
                td.nested.append(comp)
    return td


def _import(n: Node) -> ImportDecl:
    qi = _direct(n, "qualified_identifier")
    path = text(qi)
    alias = None
    if _direct(n, "as") is not None:
        ids = [c for c in n.children if c.type == "identifier"]
        alias = text(ids[-1]) if ids else None
    return ImportDecl(path, any(c.type == "*" for c in n.children), alias, False, line(n))


def parse_kotlin(path: str, source: bytes) -> ParsedFile:
    root = _parser().parse(source).root_node
    pf = ParsedFile(path=path, language="kotlin", has_errors=root.has_error,
                    line_count=source.count(b"\n") + 1)
    for c in root.children:
        if c.type == "package_header":
            pf.package, pf.package_line = text(_direct(c, "qualified_identifier")
                                               or _direct(c, "identifier")), line(c)
        elif c.type == "import":
            pf.imports.append(_import(c))
        elif c.type in ("class_declaration", "object_declaration"):
            pf.types.append(_class(c))
        elif c.type == "function_declaration":
            pf.functions.append(_function(c))
    return pf
