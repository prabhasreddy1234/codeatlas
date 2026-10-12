from app.analyzer.pipeline import analyze_repository
from app.analyzer.python_extractor import parse_python


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


def test_python_syntax_errors_are_reported():
    parsed = parse_python("broken.py", b"def broken(:\n")

    assert parsed.has_errors
    assert not parsed.types and not parsed.functions
