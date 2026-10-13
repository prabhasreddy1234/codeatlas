from types import SimpleNamespace

from app.analyzer.model import ImportDecl, ParsedFile, TypeDecl
from app.analyzer.pipeline import analyze_repository
from app.analyzer.python_extractor import parse_python
from app.analyzer.resolver import SymbolIndex, TypeInfo


def test_python_extraction_handles_declarations_imports_and_async():
    parsed = parse_python("src/shop/service.py", b"""from .models import Item as Product

class Service:
    def save(self, item: Product) -> None:
        self.repo.store(item)

async def refresh(item: Product):
    await load(item)
""")

    assert parsed.language == "python"
    assert parsed.package == "shop.service"
    assert [(imp.path, imp.alias) for imp in parsed.imports] == [
        ("shop.models.Item", "Product")]
    service = parsed.types[0]
    assert service.methods[0].params[0].type_name == "Product"
    assert service.methods[0].calls[0].receiver == "this.repo"
    assert parsed.functions[0].name == "refresh"
    assert parsed.functions[0].calls[0].name == "load"


def test_python_repository_graph_resolves_imports_and_calls(tmp_path):
    package = tmp_path / "shop"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "models.py").write_text(
        "class Store:\n"
        "    def save(self, value: str) -> None:\n"
        "        pass\n")
    (package / "service.py").write_text(
        "from .models import Store\n"
        "\n"
        "class Service:\n"
        "    def __init__(self):\n"
        "        self.store = Store()\n"
        "\n"
        "    def run(self):\n"
        "        self.store.save('item')\n"
        "\n"
        "def main():\n"
        "    Service().run()\n")

    doc = analyze_repository(tmp_path, "acme", "shop", "main", "a" * 40)
    nodes = {node.qualified_name: node for node in doc.nodes}
    nodes_by_id = {node.id: node for node in doc.nodes}
    edges = {
        (edge.type, nodes_by_id[edge.source].qualified_name,
         nodes_by_id[edge.target].qualified_name if edge.target else None)
        for edge in doc.edges
    }

    assert "shop.service.Service" in nodes
    assert "shop.service.Service.run" in nodes
    assert ("IMPORTS", "shop/service.py", "shop.models.Store") in edges
    assert ("USES", "shop.service.Service.__init__", "shop.models.Store") in edges
    assert ("CALLS", "shop.service.Service.run", "shop.models.Store.save") in edges
    assert ("CALLS", "shop.service.main", "shop.service.Service.run") in edges


def test_python_literal_and_unpacking_inference():
    parsed = parse_python("src/shop/service.py", b"""
class Service:
    def __init__(self):
        self.items = []
        self.meta = {"key": "value"}
        self.values = [1, 2]
        self.label = "ok"

    def run(self, payload):
        names = list(payload)
        first = names[0]
        return first
""")

    service = parsed.types[0]
    fields = {field.name: field.type_name for field in service.fields}
    assert fields["items"] == "list"
    assert fields["meta"] == "dict"
    assert fields["values"] == "list"
    assert fields["label"] == "str"
    assert service.methods[1].locals["names"] == "list"


def test_python_generic_bases_and_forward_reference_annotations():
    parsed = parse_python("src/shop/models.py", b"""
from typing import Generic, Literal, TypeVar

T = TypeVar("T")

class Entity:
    pass

class Parent(Generic[T]):
    pass

class Child(Parent[Entity]):
    def lookup(self, value: "Entity", values: list["Entity"],
               label: Literal["Entity"]) -> "Entity":
        pass
""")

    child = next(decl for decl in parsed.types if decl.name == "Child")
    assert [super_ref.name for super_ref in child.supers] == ["Parent"]
    assert [use.name for use in child.type_uses] == ["Parent", "Entity"]
    lookup = child.methods[0]
    assert [param.type_name for param in lookup.params] == ["Entity", "Entity", None]
    assert lookup.return_type == "Entity"
    assert [use.name for use in lookup.type_uses].count("Entity") == 3
    assert any(call.name == "TypeVar" for call in parsed.calls)


def test_resolver_module_imports_support_module_aliases():
    idx = SymbolIndex()
    pf = ParsedFile(path="pkg/models.py", language="python", package="pkg")
    info = TypeInfo(SimpleNamespace(id="type-store"), TypeDecl("class", "Store", 1, 2), pf, "pkg.models.Store")
    idx.add_type(info)
    file_pf = ParsedFile(
        path="pkg/service.py",
        language="python",
        package="pkg",
        imports=[ImportDecl("pkg.models", alias="models", line=1, module=True)],
    )

    resolved = idx.resolve_type("models.Store", idx.context(file_pf, []))

    assert resolved.info is info
    assert resolved.status == "confirmed"


def test_resolver_python_dotted_module_import_binds_only_top_level_name():
    idx = SymbolIndex()
    pf = ParsedFile(path="pkg/models.py", language="python", package="pkg")
    info = TypeInfo(SimpleNamespace(id="type-store"), TypeDecl("class", "Store", 1, 2), pf, "pkg.models.Store")
    idx.add_type(info)
    file_pf = ParsedFile(
        path="pkg/service.py",
        language="python",
        package="pkg",
        imports=[ImportDecl("pkg.models", line=1, module=True)],
    )
    context = idx.context(file_pf, [])

    assert idx.resolve_type("pkg.models.Store", context).info is info
    assert idx.resolve_type("models.Store", context).status == "unresolved"


def test_resolver_does_not_guess_through_ambiguous_or_unmatched_wildcards():
    idx = SymbolIndex()
    first_pf = ParsedFile(path="one/models.py", language="python", package="one.models")
    second_pf = ParsedFile(path="two/models.py", language="python", package="two.models")
    first = TypeInfo(SimpleNamespace(id="type-first"), TypeDecl("class", "Store", 1, 2),
                     first_pf, "one.models.Store")
    second = TypeInfo(SimpleNamespace(id="type-second"), TypeDecl("class", "Store", 1, 2),
                      second_pf, "two.models.Store")
    idx.add_type(first)
    idx.add_type(second)

    ambiguous = idx.context(ParsedFile(
        path="service.py", language="python", imports=[
            ImportDecl("one.models", wildcard=True),
            ImportDecl("two.models", wildcard=True),
        ]), [])
    assert idx.resolve_type("Store", ambiguous).status == "unresolved"

    unrelated = idx.context(ParsedFile(
        path="service.py", language="python",
        imports=[ImportDecl("external.models", wildcard=True)]), [])
    assert idx.resolve_type("Store", unrelated).status == "unresolved"


def test_python_syntax_errors_are_reported():
    parsed = parse_python("broken.py", b"def broken(:\n")

    assert parsed.has_errors
    assert not parsed.types and not parsed.functions
