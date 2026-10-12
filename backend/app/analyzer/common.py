from __future__ import annotations

import re
from typing import Iterator

from tree_sitter import Node

R_REF = re.compile(r"\bR\.(layout|id|navigation|menu)\.(\w+)")


def text(node: Node | None) -> str:
    return node.text.decode("utf-8", "replace") if node is not None else ""


def line(node: Node) -> int:
    return node.start_point[0] + 1


def end_line(node: Node) -> int:
    return node.end_point[0] + 1


def walk(node: Node) -> Iterator[Node]:
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(reversed(n.children))


def resource_refs(node: Node) -> list[tuple[str, str, int]]:
    out = []
    for n in walk(node):
        if n.type in ("field_access", "navigation_expression") and n.child_count:
            m = R_REF.fullmatch(text(n))
            if m:
                out.append((m.group(1), m.group(2), line(n)))
    return out
