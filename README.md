# CodeAtlas

Deterministic code graphs for Python and Android projects on GitHub. Sign in with GitHub, pick a repository and branch, and CodeAtlas analyzes Python, Kotlin, and Java source and shows an interactive, layered graph. **No LLM or AI API is used anywhere.**

- Backend: Python 3.11+, FastAPI, Python AST, Tree-sitter, Git CLI, SQLite + JSON files
- Frontend: React, TypeScript, Vite, React Flow (`@xyflow/react`), Dagre layout, Lucide + simple-icons

## Quick start

Prerequisites: Python 3.11+, Node 18+, git.

```bash
cp .env.example .env        # then fill in GitHub credentials (see below)
./dev.sh                    # creates the venv, installs deps, starts both servers
```

Or manually:

```bash
# Backend
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:create_app --factory --reload --port 8000

# Frontend (new terminal)
cd frontend
npm install
npm run dev
```

- Web UI: http://localhost:5173
- API: http://localhost:8000 (interactive docs: http://localhost:8000/docs)

Always open the UI via `http://localhost:5173` (the Vite dev server proxies `/api` and `/auth` to the backend, so cookies stay same-origin).

## GitHub OAuth App setup

1. GitHub → **Settings → Developer settings → OAuth Apps → New OAuth App**.
2. Fill in:
   - **Application name:** CodeAtlas (local)
   - **Homepage URL:** `http://localhost:5173`
   - **Authorization callback URL:** `http://localhost:8000/auth/github/callback`
3. Register, then **Generate a new client secret**.
4. Put the values in `.env`:
   ```
   GITHUB_CLIENT_ID=...
   GITHUB_CLIENT_SECRET=...
   ```
5. Restart the backend.

**Permissions.** The single *Connect GitHub* button requests the `repo` scope, which GitHub OAuth Apps require for private repository access (it is read/write-capable at GitHub's level; CodeAtlas only reads). The dashboard shows public repositories by default; use its **Private** filter to show private repositories. Tokens are encrypted server-side and never sent to the browser. For organization repos, the org may need to approve the OAuth app.

## How it works

1. OAuth with a signed `state` cookie; sessions are opaque HttpOnly cookies, tokens are Fernet-encrypted in SQLite.
2. POST requests require an `X-CSRF-Token` header and an allowed `Origin`. Disconnecting clears the local CodeAtlas session and revokes the GitHub OAuth grant, so reconnecting sends you through GitHub authorization again.
3. Generate: verify branch via GitHub API → shallow clone/fetch into `.codeatlas-data/repos` → checkout exact branch → record commit SHA → analyze.
4. Graphs are stored as JSON under `.codeatlas-data/graphs/{owner}/{repo}/{branch}/{sha}.json`. If the commit is unchanged, the stored graph is reused (use *Re-index* to force).
5. The UI shows a focused overview of code entry points and their neighbors; expand callers, dependencies, or members per node.

Repository code is treated as untrusted: it is only parsed, never executed; git hooks are disabled, symlinks are skipped, owner/repo/branch/paths are validated, and files over the size limit are skipped.

## Tests

```bash
cd backend && source .venv/bin/activate && python -m pytest -q
cd frontend && npm run typecheck && npm run build
```

## Static-analysis limitations

Resolution is syntax- and index-based, not compiler-grade. CodeAtlas marks each edge `confirmed`, `inferred`, `external` or `unresolved` and never invents links for unresolvable targets.

- No type inference beyond declared types: overloads are matched by arity only; chained call receivers are unresolved.
- Python is parsed with the standard-library AST. Classes, methods, functions, annotations, imports, inheritance, constructor calls, and statically traceable calls are graphed; dynamic dispatch, reflection, and runtime import behavior are not evaluated.
- Interface/abstract calls link to the interface method, not to implementations (no dynamic-dispatch resolution).
- Reflection, service locators and Koin are not analysed. Dagger/Hilt `@Provides`/`@Binds` modules are not analysed; only `@Inject` fields/constructor parameters are linked.
- Navigation: explicit `Intent(...::class)` and navigation-graph XML actions only. `findNavController().navigate(...)` and Compose `NavHost` routes are not resolved.
- AndroidManifest.xml is not parsed. Extension functions are matched by name (inferred).
- Kotlin import aliases are partially supported. The Kotlin grammar can mis-parse unusual single-line constructs.
- Android roles come from the superclass/annotation (including through in-repo hierarchy); the Repository role may be name-based and is labelled inferred.
- Structured for stronger semantics later: `SemanticProvider` in `backend/app/analyzer/resolver.py` is the hook for Kotlin compiler or Java tooling backends.
- The real GitHub OAuth round-trip requires your own OAuth App credentials; automated tests use a fake GitHub client and a local bare git remote.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "GitHub OAuth is not configured" | Set `GITHUB_CLIENT_ID`/`GITHUB_CLIENT_SECRET` in `.env`, restart backend |
| `redirect_uri` mismatch | Callback URL must be exactly `http://localhost:8000/auth/github/callback` |
| Invalid state / login loop | Use `http://localhost:5173` consistently (not 127.0.0.1); clear cookies |
| Private repos missing | Reconnect with *Connect GitHub* to grant the required access; approve the org if applicable |
| "Cannot reach backend" | Start uvicorn on port 8000 |
| `Attribute "app" not found` | Use `--factory`: `uvicorn app.main:create_app --factory` |
| Clone/checkout fails | Ensure `git` is installed and the branch exists; see error in UI |
| Empty graph | The repo may contain no Python, Kotlin, or Java sources outside ignored dirs (`build`, `.gradle`, `generated`, …) |
| Reset everything | Stop servers, delete `.codeatlas-data/` |
