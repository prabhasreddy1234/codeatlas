import json

from app.schemas.graph import GraphDocument
from app.graph.index import GraphIndex


def by_qn(doc):
    return {n.qualified_name: n for n in doc.nodes}


def edges(doc, etype, src=None, tgt=None):
    nm = {n.id: n for n in doc.nodes}
    out = []
    for e in doc.edges:
        if e.type != etype:
            continue
        s = nm[e.source].qualified_name
        t = nm[e.target].qualified_name if e.target else None
        if (src is None or s == src) and (tgt is None or t == tgt):
            out.append((s, t, e))
    return out


def test_node_types_and_locations(sample_doc):
    q = by_qn(sample_doc)
    assert q["com.example.app.data.UserRepository"].type == "interface"
    assert q["com.example.app.data.ApiService"].type == "object"
    assert q["com.example.app.data.Status"].type == "enum"
    assert q["com.example.app.data.Tracked"].type == "annotation"
    assert q["com.example.app.Helper"].type == "class"
    n = q["com.example.app.MainActivity"]
    assert n.file_path.endswith("MainActivity.kt") and n.start_line == 11 and n.end_line > n.start_line
    assert q["com.example.app.ui.UserViewModel.UserViewModel"].type == "constructor"
    assert q["com.example.app.MainActivity.onCreate"].type == "function"


def test_generated_dirs_ignored(sample_doc):
    assert not any("Ignored" in n.name for n in sample_doc.nodes)


def test_android_roles(sample_doc):
    q = by_qn(sample_doc)
    roles = {k.rsplit(".", 1)[-1]: v.roles for k, v in q.items() if v.roles}
    assert roles["MainActivity"] == ["activity"] and roles["DetailActivity"] == ["activity"]
    assert roles["ItemListFragment"] == ["fragment"]
    assert roles["UserViewModel"] == ["viewmodel"]
    assert "repository" in roles["UserRepositoryImpl"]
    assert roles["UserDao"] == ["dao"]
    assert roles["SyncWorker"] == ["worker"] and roles["SyncService"] == ["service"]
    assert roles["BootReceiver"] == ["receiver"]
    assert roles["UserScreen"] == ["composable"]
    # Roles are additive: the general type is kept
    assert q["com.example.app.MainActivity"].type == "class"
    assert "extends" in q["com.example.app.MainActivity"].role_evidence["activity"]


def test_extends_implements_overrides(sample_doc):
    assert edges(sample_doc, "IMPLEMENTS", "com.example.app.data.UserRepositoryImpl",
                 "com.example.app.data.UserRepository")
    ext = edges(sample_doc, "EXTENDS", "com.example.app.MainActivity")[0]
    assert ext[1] is None and ext[2].status == "external"
    assert ext[2].target_name == "androidx.appcompat.app.AppCompatActivity"
    ov = edges(sample_doc, "OVERRIDES", "com.example.app.data.UserRepositoryImpl.fetchUsers")
    assert ov and ov[0][1] == "com.example.app.data.UserRepository.fetchUsers" and ov[0][2].status == "confirmed"


def test_imports(sample_doc):
    imp = edges(sample_doc, "IMPORTS")
    conf = [(s.rsplit("/", 1)[-1], t) for s, t, e in imp if t]
    assert ("MainActivity.kt", "com.example.app.data.Item") in conf
    ext = [e for s, t, e in imp if t is None]
    assert ext and all(e.status == "external" for e in ext)


def test_call_resolution(sample_doc):
    on_create = "com.example.app.MainActivity.onCreate"
    c = edges(sample_doc, "CALLS", on_create, "com.example.app.ui.UserViewModel.refresh")
    assert c and c[0][2].status == "confirmed" and c[0][2].line == 18
    assert edges(sample_doc, "CALLS", on_create, "com.example.app.MainActivity.render")
    assert edges(sample_doc, "CALLS", "com.example.app.MainActivity.render", "com.example.app.Helper.log")
    # Java -> Kotlin interface method call through a typed field/param
    assert edges(sample_doc, "CALLS", "com.example.app.ui.UserViewModel.refresh",
                 "com.example.app.data.UserRepository.fetchUsers")
    assert edges(sample_doc, "CALLS", "com.example.app.ui.DetailActivity.onCreate",
                 "com.example.app.Helper.log")


def test_unresolved_calls_are_explicit_and_never_linked(sample_doc):
    missing = [e for e in sample_doc.edges if e.type == "CALLS" and e.status == "unresolved"]
    names = {e.target_name for e in missing}
    assert {"mysteryCall", "unknownFramework", "repository.nothingHere"} <= names
    assert all(e.target is None and e.provenance for e in missing)
    assert sample_doc.stats["unresolved_calls"] == len(missing)


def test_duplicate_class_names_in_different_packages(sample_doc):
    q = by_qn(sample_doc)
    a, b = q["com.example.app.data.Item"], q["com.example.app.other.Item"]
    assert a.id != b.id
    # explicit import -> data.Item; same package -> other.Item
    assert edges(sample_doc, "USES", "com.example.app.ui.ItemAdapter", a.qualified_name)
    assert not edges(sample_doc, "USES", "com.example.app.ui.ItemAdapter", b.qualified_name)
    assert edges(sample_doc, "USES", "com.example.app.other.ItemHolder", b.qualified_name)
    assert not edges(sample_doc, "USES", "com.example.app.other.ItemHolder", a.qualified_name)


def test_injects_and_navigation(sample_doc):
    inj = edges(sample_doc, "INJECTS", "com.example.app.ui.UserViewModel")
    assert [t for _, t, _ in inj] == ["com.example.app.data.UserRepository"]
    assert edges(sample_doc, "INJECTS", "com.example.app.data.UserRepositoryImpl",
                 "com.example.app.data.UserDao")
    nav = {(s.rsplit(".", 1)[-1], t.rsplit(".", 1)[-1]) for s, t, _ in edges(sample_doc, "NAVIGATES_TO")}
    assert ("onCreate", "DetailActivity") in nav
    assert ("ItemListFragment", "ItemDetailFragment") in nav


def test_hierarchy_contains(sample_doc):
    nm = {n.id: n for n in sample_doc.nodes}
    chain = []
    cur = by_qn(sample_doc)["com.example.app.MainActivity.onCreate"]
    while cur:
        chain.append(cur.type)
        cur = nm.get(cur.parent_id)
    assert chain == ["function", "class", "file", "package", "repository"]


def test_json_roundtrip_and_metadata(sample_doc):
    raw = sample_doc.model_dump_json()
    back = GraphDocument.model_validate(json.loads(raw))
    assert back.repository.id == "acme/sample" and back.branch == "main" and back.commit_sha == "a" * 40
    assert back.indexed_at and back.analyzer.llm_used is False
    assert len(back.nodes) == len(sample_doc.nodes) and len(back.edges) == len(sample_doc.edges)
    assert all(e.status in ("confirmed", "inferred", "external", "unresolved") for e in back.edges)


def test_index_queries(sample_doc):
    idx = GraphIndex(sample_doc)
    complete = idx.overview()
    assert len(complete["nodes"]) == len(sample_doc.nodes)
    assert len(complete["edges"]) >= len(sample_doc.edges)
    assert {node["id"] for node in complete["nodes"]} == {node.id for node in sample_doc.nodes}
    ov = idx.overview(50)
    by_name = {n["qualified_name"]: n for n in ov["nodes"]}
    assert "com.example.app.MainActivity.onCreate" in by_name
    assert "com.example.app.ui.UserViewModel.refresh" in by_name
    assert "com.example.app.data.UserRepositoryImpl.fetchUsers" in by_name
    assert "com.example.app.data.UserDao.all" in by_name
    assert by_name["com.example.app.MainActivity.onCreate"]["level"] == 0
    assert "entry_point" in by_name["com.example.app.MainActivity.onCreate"]["roles"]
    assert len(ov["levels"]) > 1
    assert ov["total_reachable_nodes"] >= len(ov["nodes"])
    assert any(edge["type"] == "NAVIGATES_TO" and
               edge["target"] == by_name["com.example.app.ui.DetailActivity.onCreate"]["id"]
               for edge in ov["edges"])
    assert any(edge["status"] == "inferred" and "runtime dispatch" in edge["provenance"]
               for edge in ov["edges"])
    limited = idx.overview(1)
    assert limited["truncated"] and len(limited["nodes"]) == 1
    q = by_qn(sample_doc)
    nb = idx.neighbors(q["com.example.app.ui.UserViewModel"].id, "out")
    assert "UserRepository" in {n["name"] for n in nb["nodes"]}
    up = idx.neighbors(q["com.example.app.ui.UserViewModel"].id, "in")
    assert {"MainActivity", "UserScreen"} <= {n["name"] for n in up["nodes"]}
    assert idx.search("userrepo")[0]["name"].startswith("UserRepository")
    det = idx.details(q["com.example.app.MainActivity"].id)
    assert det["node"]["file_path"].endswith("MainActivity.kt") and det["outgoing_total"] > 0
