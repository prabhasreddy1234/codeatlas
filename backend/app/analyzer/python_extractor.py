"""Extract Python declarations and relationships with the standard-library AST."""
from __future__ import annotations

import ast
from pathlib import PurePosixPath

from .model import (CallSite, FieldDecl, FuncDecl, ImportDecl, Param, ParsedFile,
                    SuperRef, TypeDecl, TypeUse)


_TYPE_WRAPPERS = {"Annotated", "ClassVar", "Final", "Literal", "Optional", "Union"}
_BUILTIN_TYPES = {
    "bool", "bytes", "complex", "dict", "float", "frozenset", "int", "list",
    "memoryview", "object", "set", "str", "tuple", "type",
}
_BUILTIN_FACTORIES = {
    "list", "dict", "set", "tuple", "frozenset", "deque", "defaultdict",
    "OrderedDict", "Counter",
}


def _expr_name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _expr_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _type_names(node: ast.AST | None) -> list[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        name = _expr_name(node)
        return [name] if name else []
    if isinstance(node, ast.Subscript):
        return _type_names(node.value) + _type_names(node.slice)
    if isinstance(node, (ast.Tuple, ast.List)):
        return [name for element in node.elts for name in _type_names(element)]
    if isinstance(node, ast.BinOp):
        return _type_names(node.left) + _type_names(node.right)
    return []


def _annotation_names(node: ast.AST | None, depth: int = 0) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        if depth >= 4:
            return []
        try:
            expression = ast.parse(node.value, mode="eval").body
        except SyntaxError:
            return []
        return _annotation_names(expression, depth + 1)
    if isinstance(node, ast.Subscript):
        names = _type_names(node.value)
        if _expr_name(node.value).rsplit(".", 1)[-1] == "Literal":
            if isinstance(node.slice, ast.Tuple):
                return names + [name for arg in node.slice.elts
                                if not (isinstance(arg, ast.Constant)
                                        and isinstance(arg.value, str))
                                for name in _annotation_names(arg, depth)]
            if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                return names
        return names + _annotation_names(node.slice, depth)
    if isinstance(node, (ast.Tuple, ast.List)):
        return [name for element in node.elts for name in _annotation_names(element, depth)]
    if isinstance(node, ast.BinOp):
        return _annotation_names(node.left, depth) + _annotation_names(node.right, depth)
    return _type_names(node)


def _line(node: ast.AST) -> int:
    return getattr(node, "lineno", 1)


def _end_line(node: ast.AST) -> int:
    return getattr(node, "end_lineno", _line(node))


def _module_name(path: str) -> str:
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts and parts[0] == "src":
        parts.pop(0)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) or PurePosixPath(path).stem


def _relative_module(current: str, module: str, level: int, is_package: bool) -> str:
    if not level:
        return module
    package_parts = current.split(".") if current else []
    if not is_package:
        package_parts = package_parts[:-1]
    if level > 1:
        package_parts = package_parts[:max(0, len(package_parts) - level + 1)]
    return ".".join([*package_parts, *([module] if module else [])])


def _annotation_type(node: ast.AST | None) -> str | None:
    names = _annotation_names(node)
    return next((name for name in names
                 if name.rsplit(".", 1)[-1] not in _TYPE_WRAPPERS
                 and name.rsplit(".", 1)[-1] not in _BUILTIN_TYPES), None)


def _literal_type(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant):
        if node.value is None:
            return "None"
        if isinstance(node.value, bool):
            return "bool"
        if isinstance(node.value, int):
            return "int"
        if isinstance(node.value, float):
            return "float"
        if isinstance(node.value, complex):
            return "complex"
        if isinstance(node.value, str):
            return "str"
        if isinstance(node.value, bytes):
            return "bytes"
        return None
    if isinstance(node, (ast.List, ast.Tuple)):
        return "list" if isinstance(node, ast.List) else "tuple"
    if isinstance(node, ast.Set):
        return "set"
    if isinstance(node, ast.Dict):
        return "dict"
    if isinstance(node, ast.Call):
        callable_ = node.func
        if isinstance(callable_, ast.Name):
            name = callable_.id
            if name in _BUILTIN_FACTORIES:
                return name
            if name[:1].isupper():
                return name
        elif isinstance(callable_, ast.Attribute):
            name = callable_.attr
            if name in _BUILTIN_FACTORIES:
                return name
    return None


def _receiver(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        if node.id in ("self", "cls"):
            return "this"
        return node.id
    if isinstance(node, ast.Attribute):
        value = _receiver(node.value)
        if value == "<complex>":
            return value
        return f"{value}.{node.attr}"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id[:1].isupper():
        return node.func.id
    return "<complex>"


class _BodyVisitor(ast.NodeVisitor):
    def __init__(self, target: FuncDecl | TypeDecl | ParsedFile,
                 fields: list[FieldDecl] | None = None):
        self.target = target
        self.fields = fields

    def visit_FunctionDef(self, _node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, _node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, _node: ast.ClassDef) -> None:
        return

    def visit_Lambda(self, _node: ast.Lambda) -> None:
        return

    def visit_Call(self, node: ast.Call) -> None:
        fn = node.func
        if isinstance(fn, ast.Name):
            name, receiver = fn.id, None
        elif isinstance(fn, ast.Attribute):
            name, receiver = fn.attr, _receiver(fn.value)
        else:
            name, receiver = _expr_name(fn), None
        if name:
            kind = "new" if receiver is None and name[:1].isupper() else "call"
            self.target.calls.append(CallSite(
                name, receiver, _line(node), len(node.args) + len(node.keywords), kind))
            if kind == "new" and not isinstance(self.target, ParsedFile):
                self.target.type_uses.append(TypeUse(name, _line(node), "instantiation"))
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        names = _annotation_names(node.annotation)
        for name in names:
            self.target.type_uses.append(TypeUse(name, _line(node)))
        type_name = _annotation_type(node.annotation)
        self._record_assignment(node.target, type_name, _line(node))
        if isinstance(node.value, ast.AST):
            self.visit(node.value)

    def visit_Assign(self, node: ast.Assign) -> None:
        inferred = self._called_type(node.value)
        for target in node.targets:
            self._record_assignment(target, inferred, _line(node))
        self.visit(node.value)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self._record_assignment(node.target, self._called_type(node.value), _line(node))
        self.visit(node.value)

    def _record_assignment(self, target: ast.AST, type_name: str | None, line: int) -> None:
        if isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self._record_assignment(elt, type_name, line)
            return
        if isinstance(target, ast.Starred):
            self._record_assignment(target.value, type_name, line)
            return
        if isinstance(target, ast.Name) and isinstance(self.target, FuncDecl) and type_name:
            self.target.locals[target.id] = type_name
        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) \
                and target.value.id in ("self", "cls") and self.fields is not None and type_name:
            self.fields.append(FieldDecl(target.attr, type_name, line))

    @staticmethod
    def _called_type(value: ast.AST | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, ast.AST):
            return _literal_type(value)
        return None


def _function(node: ast.FunctionDef | ast.AsyncFunctionDef,
              owner: str | None = None) -> tuple[FuncDecl, list[FieldDecl]]:
    kind = "constructor" if owner and node.name == "__init__" else "function"
    args = node.args
    all_args = [*args.posonlyargs, *args.args, *args.kwonlyargs]
    if args.vararg:
        all_args.append(args.vararg)
    if args.kwarg:
        all_args.append(args.kwarg)
    if owner:
        all_args = [arg for arg in all_args if arg.arg not in ("self", "cls")]
    params = [Param(arg.arg, _annotation_type(arg.annotation)) for arg in all_args]
    annotations = [_expr_name(dec) for dec in node.decorator_list if _expr_name(dec)]
    ret = _annotation_type(node.returns)
    fd = FuncDecl(node.name, kind, _line(node), _end_line(node), params, ret, annotations)
    for arg in all_args:
        for name in _annotation_names(arg.annotation):
            fd.type_uses.append(TypeUse(name, _line(arg)))
    for name in _annotation_names(node.returns):
        fd.type_uses.append(TypeUse(name, _line(node)))
    fd.type_uses.extend(TypeUse(name, _line(node), "annotation") for name in annotations)
    fields: list[FieldDecl] = []
    visitor = _BodyVisitor(fd, fields if kind == "constructor" else None)
    for statement in node.body:
        visitor.visit(statement)
    return fd, fields


def _class(node: ast.ClassDef) -> TypeDecl:
    td = TypeDecl("class", node.name, _line(node), _end_line(node))
    for base in node.bases:
        name = _expr_name(base.value if isinstance(base, ast.Subscript) else base)
        if name:
            td.supers.append(SuperRef(name, _line(base), True))
        for type_name in _type_names(base):
            td.type_uses.append(TypeUse(type_name, _line(base)))
    for decorator in node.decorator_list:
        name = _expr_name(decorator)
        if name:
            td.annotations.append(name)
            td.type_uses.append(TypeUse(name, _line(decorator), "annotation"))
    for statement in node.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            method, fields = _function(statement, node.name)
            td.methods.append(method)
            td.fields.extend(fields)
        elif isinstance(statement, ast.ClassDef):
            td.nested.append(_class(statement))
        else:
            if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                type_name = _annotation_type(statement.annotation)
                td.fields.append(FieldDecl(statement.target.id, type_name, _line(statement)))
                td.type_uses.extend(TypeUse(n, _line(statement))
                                    for n in _type_names(statement.annotation))
            _BodyVisitor(td).visit(statement)
    return td


def _imports(tree: ast.Module, module_name: str, path: str) -> list[ImportDecl]:
    imports: list[ImportDecl] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".", 1)[0]
                imports.append(ImportDecl(alias.name, alias=bound if alias.asname or "." in alias.name else None,
                                          line=_line(node), module=True))
        elif isinstance(node, ast.ImportFrom):
            base = _relative_module(
                module_name, node.module or "", node.level,
                PurePosixPath(path).name == "__init__.py")
            for alias in node.names:
                if alias.name == "*":
                    imports.append(ImportDecl(base, wildcard=True, line=_line(node)))
                else:
                    full = ".".join(part for part in (base, alias.name) if part)
                    imports.append(ImportDecl(full, alias=alias.asname, line=_line(node)))
    return imports


def parse_python(path: str, source: bytes) -> ParsedFile:
    module_name = _module_name(path)
    pf = ParsedFile(
        path=path, language="python", package=module_name,
        line_count=source.count(b"\n") + 1)
    try:
        tree = ast.parse(source, filename=path, type_comments=True)
    except (SyntaxError, UnicodeDecodeError):
        pf.has_errors = True
        return pf
    pf.imports = _imports(tree, module_name, path)
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            pf.types.append(_class(node))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function, _ = _function(node)
            pf.functions.append(function)
        elif not isinstance(node, (ast.Import, ast.ImportFrom)):
            _BodyVisitor(pf).visit(node)
    return pf
