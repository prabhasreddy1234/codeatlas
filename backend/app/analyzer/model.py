"""Language-neutral syntax facts extracted from one source file."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ImportDecl:
    path: str
    wildcard: bool = False
    alias: Optional[str] = None
    static: bool = False
    line: int = 0


@dataclass
class TypeUse:
    name: str
    line: int
    context: str = "type"  # type | instantiation | annotation | class-literal


@dataclass
class CallSite:
    name: str
    receiver: Optional[str]  # None, "this", "super", "ident", "this.field", "a.b" or "<complex>"
    line: int
    argc: int = 0
    kind: str = "call"  # call | new


@dataclass
class Param:
    name: str
    type_name: Optional[str] = None


@dataclass
class FieldDecl:
    name: str
    type_name: Optional[str]
    line: int
    annotations: list[str] = field(default_factory=list)


@dataclass
class SuperRef:
    name: str
    line: int
    ctor_call: Optional[bool] = None  # Kotlin: True when `Super()` invoked; Java: explicit


@dataclass
class FuncDecl:
    name: str
    kind: str  # function | constructor
    start: int
    end: int
    params: list[Param] = field(default_factory=list)
    return_type: Optional[str] = None
    annotations: list[str] = field(default_factory=list)
    modifiers: set[str] = field(default_factory=set)
    calls: list[CallSite] = field(default_factory=list)
    type_uses: list[TypeUse] = field(default_factory=list)
    locals: dict[str, str] = field(default_factory=dict)
    intents: list[tuple[str, int]] = field(default_factory=list)
    resource_refs: list[tuple[str, str, int]] = field(default_factory=list)
    receiver_type: Optional[str] = None  # Kotlin extension receiver
    injected_params: bool = False  # annotated @Inject constructor etc.


@dataclass
class TypeDecl:
    kind: str  # class | interface | object | enum | annotation
    name: str
    start: int
    end: int
    annotations: list[str] = field(default_factory=list)
    modifiers: set[str] = field(default_factory=set)
    supers: list[SuperRef] = field(default_factory=list)
    fields: list[FieldDecl] = field(default_factory=list)
    methods: list[FuncDecl] = field(default_factory=list)
    nested: list["TypeDecl"] = field(default_factory=list)
    type_uses: list[TypeUse] = field(default_factory=list)
    calls: list[CallSite] = field(default_factory=list)  # initializers / init blocks
    intents: list[tuple[str, int]] = field(default_factory=list)
    resource_refs: list[tuple[str, str, int]] = field(default_factory=list)
    is_companion: bool = False


@dataclass
class ParsedFile:
    path: str
    language: str
    package: str = ""
    package_line: int = 0
    imports: list[ImportDecl] = field(default_factory=list)
    types: list[TypeDecl] = field(default_factory=list)
    functions: list[FuncDecl] = field(default_factory=list)
    line_count: int = 0
    has_errors: bool = False
