import pytest

from app.errors import AppError
from app.github.git_service import GitService
from app.github.validation import validate_branch, validate_owner, validate_repo
from app.storage.db import Database
from app.storage.graph_store import GraphStore
from tests.conftest import git


def test_store_roundtrip_and_latest(tmp_path, sample_doc):
    store = GraphStore(tmp_path, Database(tmp_path / "x.db"))
    path = store.save(sample_doc)
    assert path.exists() and tmp_path in path.parents
    assert store.has("ACME", "Sample", "main", "a" * 40)
    loaded = store.load("acme", "sample", "main", "a" * 40)
    assert loaded.commit_sha == sample_doc.commit_sha and len(loaded.nodes) == len(sample_doc.nodes)
    assert store.latest_sha("acme", "sample", "main") == "a" * 40
    assert store.latest_sha("acme", "sample", "other") is None


@pytest.mark.parametrize("branch", ["--upload-pack=x", "../x", "a..b", "-x", "a b", "x;rm", "a/", "/a", "a.lock", ""])
def test_unsafe_branches_rejected(branch):
    with pytest.raises(AppError):
        validate_branch(branch)


@pytest.mark.parametrize("fn,val", [(validate_owner, "../x"), (validate_owner, "a/b"), (validate_repo, ".."),
                                    (validate_repo, "a b"), (validate_repo, "x.git")])
def test_unsafe_names_rejected(fn, val):
    with pytest.raises(AppError):
        fn(val)


def test_branch_checkout_and_commit_tracking(settings, remote_repo):
    svc = GitService(settings)
    d, sha_main = svc.sync("acme", "sample", "main", None)
    assert sha_main == git(remote_repo["bare"], "rev-parse", "refs/heads/main")
    assert not (d / "app/src/main/java/com/example/app/Extra.kt").exists()
    d2, sha_feat = svc.sync("acme", "sample", "feature/extra", None)
    assert d2 == d and sha_feat != sha_main
    assert (d / "app/src/main/java/com/example/app/Extra.kt").exists()
    assert git(d, "rev-parse", "--abbrev-ref", "HEAD") == "feature/extra"
    _, back = svc.sync("acme", "sample", "main", None)
    assert back == sha_main and not (d / "app/src/main/java/com/example/app/Extra.kt").exists()


def test_missing_branch_error(settings):
    with pytest.raises(AppError) as e:
        GitService(settings).sync("acme", "sample", "nope", None)
    assert e.value.code == "git_failed" and "Branch not found" in e.value.message


def test_clone_stays_in_workspace(settings):
    svc = GitService(settings)
    assert svc.base in svc.repo_dir("acme", "sample").parents
    with pytest.raises(AppError):
        svc.repo_dir("acme", "..")
