<div align="center">
  <img src="assets/codeatlas-logo.svg" alt="CodeAtlas graph logo" width="104" height="104" />
  <h1>CodeAtlas</h1>
  <p><strong>See how your codebase connects.</strong></p>
  <p>Turn Python, Java, and Kotlin repositories into interactive maps of their code structure.</p>
</div>

---

CodeAtlas is a local-first code intelligence tool for exploring how modules, classes, functions, and calls connect across a repository. It analyzes source code into a deterministic graph and presents that graph in an interactive browser-based workspace.

CodeAtlas uses static analysis rather than LLMs or external AI APIs. Repository files are parsed, not executed.

## What you can do

- Explore entry points, calls, dependencies, classes, and members in a repository graph.
- Follow connections across Python, Java, and Kotlin source files.
- Inspect graph relationships labeled as confirmed, inferred, external, or unresolved.
- Browse repositories and branches through GitHub OAuth, including private repositories when authorized.
- Filter and inspect graph nodes, neighbors, and metadata in an interactive React Flow canvas.
- Analyze repository structure without running project code.

## How it works

1. Sign in with GitHub and select a repository and branch.
2. CodeAtlas checks out the selected revision into its local cache.
3. Static analyzers parse supported source files and build a code graph.
4. The graph is saved as JSON and reused when the repository commit has not changed.

Repository content is treated as untrusted. CodeAtlas does not execute it; Git hooks are disabled, symlinks are skipped, paths are validated, and oversized files are ignored.

## Technology

| Area | Stack |
|---|---|
| Backend | Python 3.11+, FastAPI, SQLite |
| Analysis | Python AST and custom Java/Kotlin extractors |
| Frontend | React, TypeScript, Vite |
| Visualization | React Flow |
| Repository access | Git CLI and GitHub OAuth |

Generated graph data and cached repositories are stored locally under `.codeatlas-data/`.

## Get started

### Prerequisites

- Python 3.11 or later
- Node.js 18 or later
- Git
- A GitHub OAuth App (for repository sign-in)

### Configure GitHub OAuth

1. In GitHub, open **Settings → Developer settings → OAuth Apps → New OAuth App**.
2. Configure the application:
   - **Application name:** `CodeAtlas (local)`
   - **Homepage URL:** `http://localhost:5173`
   - **Authorization callback URL:** `http://localhost:8000/auth/github/callback`
3. Create a client secret and set both credentials in the project-root `.env` file:

   ```dotenv
   GITHUB_CLIENT_ID=your_client_id
   GITHUB_CLIENT_SECRET=your_client_secret
   ```

The Connect GitHub flow requests the `repo` scope for private repository access. Tokens are encrypted server-side and are not exposed to the browser.

### Run the app

From the project root:

```bash
cp .env.example .env
./dev.sh
```

The bootstrap script prepares the Python environment, installs backend dependencies, and starts the backend and frontend services.

To start the services manually:

```bash
# Terminal 1: backend
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:create_app --factory --reload --port 8000
```

```bash
# Terminal 2: frontend
cd frontend
npm install
npm run dev
```

Open the app at **[http://localhost:5173](http://localhost:5173)**. The API documentation is available at **[http://localhost:8000/docs](http://localhost:8000/docs)**. The Vite development server proxies `/api` and `/auth` to the backend so authentication cookies remain same-origin when using the frontend.

## Development

Run the backend tests and frontend checks:

```bash
cd backend
source .venv/bin/activate
python -m pytest -q
```

```bash
cd frontend
npm run typecheck
npm run build
```

## Analysis scope and limitations

CodeAtlas is syntax-driven, deterministic, and designed to be explicit about uncertainty; it is not a compiler or a runtime execution engine. It does not create links when a target cannot be resolved confidently.

Current limitations include:

- No deep type inference beyond declared types
- Overload resolution by arity only
- Limited handling of chained call receivers
- Python analysis uses the standard-library AST
- No evaluation of dynamic dispatch, reflection, or runtime import behavior
- Partial handling of Android navigation and dependency-injection patterns
- Simplified matching for Kotlin extension functions and import aliases
- Repository role labels may be inferred rather than fully semantic

## Troubleshooting

| Problem | What to check |
|---|---|
| GitHub OAuth is not configured | Set `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` in `.env`, then restart the backend. |
| Redirect URI mismatch | Use exactly `http://localhost:8000/auth/github/callback` in the OAuth App settings. |
| Invalid state or login loop | Use `http://localhost:5173` consistently and clear the browser cookies. |
| Private repositories are missing | Reconnect with GitHub and approve access for the relevant organization. |
| Backend is unreachable | Start the API on port 8000. |
| `Attribute "app" not found` | Start Uvicorn with `uvicorn app.main:create_app --factory`. |
| Clone or checkout fails | Check that Git is installed and the selected branch exists. |
| Graph is empty | Check that the repository contains supported Python, Kotlin, or Java sources outside ignored directories. |

To clear cached repositories and graph data, stop the services and remove `.codeatlas-data/`.

## Project layout

```text
backend/          Python API and analysis engine
frontend/         React application and graph visualization
assets/           Project branding assets
dev.sh            Local development bootstrap
```

## License

CodeAtlas is open source under the [MIT License](LICENSE).
