import time

from fastapi.testclient import TestClient


def wait_ready(client, branch="main", timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        s = client.get("/api/graphs/acme/sample/status", params={"branch": branch}).json()
        if s["state"] in ("ready", "failed"):
            return s
        time.sleep(0.1)
    raise AssertionError("indexing timed out")


def gen(client, branch="main", force=False):
    return client.post("/api/graphs/generate", json={"owner": "acme", "repo": "sample", "branch": branch,
                                                      "force": force})


def test_unauthenticated_requests(app):
    c = TestClient(app, base_url="http://localhost:8000")
    me = c.get("/api/auth/me").json()
    assert me == {"authenticated": False, "oauth_configured": True}
    r = c.get("/api/github/repos")
    assert r.status_code == 401 and r.json()["error"]["code"] == "not_authenticated"


def test_me_hides_token(client):
    body = client.get("/api/auth/me").json()
    assert body["user"]["login"] == "octo" and body["private_access"] is True
    assert "gho_faketoken" not in client.get("/api/auth/me").text


def test_csrf_required_for_post(client):
    h = dict(client.headers)
    c = TestClient(client.app, base_url="http://localhost:8000")
    c.cookies.set("codeatlas_session", client.cookies["codeatlas_session"])
    r = c.post("/api/graphs/generate", json={"owner": "acme", "repo": "sample", "branch": "main"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"
    r = client.post("/api/graphs/generate", headers={"Origin": "http://evil.example"},
                    json={"owner": "acme", "repo": "sample", "branch": "main"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "bad_origin"


def test_oauth_state_validation(app):
    c = TestClient(app, base_url="http://localhost:8000", follow_redirects=False)
    r = c.get("/auth/github")
    assert r.status_code == 302 and "scope=repo" in r.headers["location"] and "state=" in r.headers["location"]
    bad = c.get("/auth/github/callback", params={"code": "x", "state": "forged"})
    assert bad.status_code == 302 and "auth_error=invalid_state" in bad.headers["location"]
    nocookie = TestClient(app, follow_redirects=False).get("/auth/github/callback", params={"code": "x", "state": "s"})
    assert "auth_error=invalid_state" in nocookie.headers["location"]


def test_oauth_not_configured(tmp_path):
    from app.config import Settings
    from app.main import create_app
    app = create_app(Settings(workspace_dir=tmp_path, secret_key="k" * 32, _env_file=None))
    r = TestClient(app).get("/auth/github", follow_redirects=False)
    assert r.status_code == 503 and r.json()["error"]["code"] == "oauth_not_configured"


def test_repos_and_branches(client):
    public = client.get("/api/github/repos").json()["repositories"]
    assert [repo["full_name"] for repo in public] == ["acme/sample"]
    private = client.get("/api/github/repos", params={"visibility": "private"}).json()["repositories"]
    assert [repo["full_name"] for repo in private] == ["acme/private-sample"]
    assert client.get("/api/github/repos", params={"visibility": "all"}).status_code == 422
    assert client.get("/api/github/repos/acme/sample/branches").json()["branches"][0]["name"] == "main"
    assert client.get("/api/github/repos/../x/branches").status_code in (400, 404)


def test_private_repos_require_private_scope(app):
    from fastapi.testclient import TestClient
    client = TestClient(app, base_url="http://localhost:8000")
    sess = app.state.sessions.create("public-token", {"login": "octo"}, "")
    client.cookies.set("codeatlas_session", sess.id)
    repos = client.get("/api/github/repos", params={"visibility": "private"}).json()["repositories"]
    assert repos == []


def test_generate_and_cache(client, remote_repo):
    r = gen(client)
    assert r.status_code == 200
    s = wait_ready(client)
    assert s["state"] == "ready" and not s["cached"] and len(s["commit_sha"]) == 40
    g = client.get("/api/graphs/acme/sample", params={"branch": "main"}).json()
    assert g["commit_sha"] == s["commit_sha"] and g["stats"]["nodes"] > 20
    assert g["analyzer"]["llm_used"] is False
    names = {n["name"] for n in g["overview"]["nodes"]}
    assert "MainActivity" in names
    # unchanged commit: served from storage without re-indexing
    indexed_at = g["indexed_at"]
    again = gen(client).json()
    assert again["state"] == "ready" and again["cached"] is True
    g2 = client.get("/api/graphs/acme/sample", params={"branch": "main"}).json()
    assert g2["indexed_at"] == indexed_at
    # node details + neighbors
    nid = next(n["id"] for n in g["overview"]["nodes"] if n["name"] == "UserViewModel")
    d = client.get(f"/api/graphs/acme/sample/nodes/{nid}", params={"branch": "main"}).json()
    assert d["node"]["file_path"].endswith("UserViewModel.kt") and d["node"]["start_line"] == 8
    nb = client.get(f"/api/graphs/acme/sample/neighbors/{nid}", params={"branch": "main", "direction": "in"}).json()
    assert "MainActivity" in {n["name"] for n in nb["nodes"]}
    sr = client.get("/api/graphs/acme/sample/search", params={"branch": "main", "q": "fetchusers"}).json()
    assert any(x["name"] == "fetchUsers" for x in sr["results"])
    assert client.get("/api/graphs/acme/sample/export", params={"branch": "main"}).status_code == 200


def test_new_commit_reindexes_and_branches_are_separate(client, remote_repo):
    gen(client)
    first = wait_ready(client)
    gen(client, "feature/extra")
    feat = wait_ready(client, "feature/extra")
    assert feat["commit_sha"] != first["commit_sha"]
    g = client.get("/api/graphs/acme/sample", params={"branch": "feature/extra"}).json()
    assert g["branch"] == "feature/extra" and g["commit_sha"] == feat["commit_sha"]
    res = client.get("/api/graphs/acme/sample/search", params={"branch": "feature/extra", "q": "Extra"}).json()
    assert any(r["name"] == "Extra" for r in res["results"])
    res = client.get("/api/graphs/acme/sample/search", params={"branch": "main", "q": "Extra"}).json()
    assert not any(r["name"] == "Extra" for r in res["results"])


def test_force_regenerates(client):
    gen(client)
    wait_ready(client)
    r = gen(client, force=True).json()
    assert r["state"] in ("queued", "running", "ready") and r["cached"] is False
    assert wait_ready(client)["state"] == "ready"


def test_error_handling(client):
    r = gen(client, "does-not-exist")
    s = r.json()
    if r.status_code == 200:
        s = wait_ready(client, "does-not-exist")
        assert s["state"] == "failed" and s["error"]["code"]
    bad = client.post("/api/graphs/generate", json={"owner": "acme", "repo": "sample", "branch": "--x"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_branch"
    missing = client.post("/api/graphs/generate", json={"owner": "other", "repo": "sample", "branch": "main"})
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "github_not_found"
    assert client.post("/api/graphs/generate", json={"owner": "acme"}).status_code == 422
    nf = client.get("/api/graphs/acme/sample", params={"branch": "never"})
    assert nf.status_code == 404 and nf.json()["error"]["code"] == "graph_not_found"
    assert client.get("/api/graphs/acme/sample/nodes/zzz", params={"branch": "main"}).status_code == 404


def test_graph_access_is_per_user(app, client):
    gen(client)
    wait_ready(client)
    other = TestClient(app, base_url="http://localhost:8000")
    s = app.state.sessions.create("t2", {"login": "mallory"}, "")
    other.cookies.set("codeatlas_session", s.id)
    r = other.get("/api/graphs/acme/sample", params={"branch": "main"})
    assert r.status_code == 404


def test_logout(client):
    session_id = client.cookies["codeatlas_session"]
    r = client.post("/api/auth/logout")
    assert r.status_code == 200
    assert not client.app.state.sessions.get(session_id)
    assert client.get("/api/auth/me").json()["authenticated"] is False
