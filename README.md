# CodeAtlas

CodeAtlas is a local-first code intelligence tool for Python and Android repositories. It authenticates with GitHub, analyzes source code into a deterministic dependency graph, and presents the result as an interactive map of entry points, calls, dependencies, and members.

The platform is designed for code exploration and architectural understanding without relying on LLMs or external AI APIs. It works entirely with local parsing, repository metadata, and graph generation.

## Why CodeAtlas

- Understand the structure of a codebase before making broad refactors.
- Trace how modules, classes, and functions connect across Python, Java, and Kotlin.
- Inspect a repository graph without executing project code.
- Keep analysis deterministic and explainable instead of model-driven.

## Key capabilities

- GitHub OAuth sign-in with repository selection and branch browsing
- Static analysis of Python, Java, and Kotlin project files
- Graph edges labeled as confirmed, inferred, external, or unresolved
- Repository-level filtering for public and private access
- Interactive inspection of nodes, neighbors, and graph metadata
- Browser-based visualization using a React Flow canvas

## Architecture

- Backend: Python 3.11+, FastAPI, SQLite, Git CLI, static AST-based analysis
- Frontend: React, TypeScript, Vite, React Flow, Lucide icons, simple-icons
- Storage: cached repository data and generated graph JSON under `.codeatlas-data/`

## Prerequisites

- Python 3.11+
- Node.js 18+
- Git

## Quick start

Start with the bundled script:

```bash
cp .env.example .env
./dev.sh
```

The script prepares the Python virtual environment, installs dependencies, and starts both the backend and frontend services.

### Manual setup

Backend:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:create_app --factory --reload --port 8000
```

Frontend (new terminal):

```bash
cd frontend
npm install
npm run dev
```

Then open:

- UI: http://localhost:5173
- API docs: http://localhost:8000/docs

The Vite dev server proxies `/api` and `/auth` to the backend, so browser cookies remain same-origin and authentication works correctly when you use the UI on port 5173.

## GitHub OAuth setup

1. Go to GitHub → Settings → Developer settings → OAuth Apps → New OAuth App.
2. Configure the app with:
   - Application name: `CodeAtlas (local)`
   - Homepage URL: `http://localhost:5173`
   - Authorization callback URL: `http://localhost:8000/auth/github/callback`
3. Save the app and generate a client secret.
4. Add the values to your `.env` file:

```bash
GITHUB_CLIENT_ID=your_client_id
GITHUB_CLIENT_SECRET=your_client_secret
```

5. Restart the backend service.

### Permissions

The Connect GitHub flow requests the `repo` scope, which GitHub requires for private repository access. CodeAtlas reads repository contents and does not execute code from the repository. Tokens are encrypted server-side and are never exposed to the browser.

## How the analysis works

1. The app authenticates the user and validates the GitHub OAuth state.
2. It fetches repository metadata and checks out the selected branch.
3. It shallow clones or reuses a cached repository under `.codeatlas-data/repos`.
4. It parses source files and builds a code graph from the repository structure.
5. It stores results as JSON in `.codeatlas-data/graphs/` and reuses cached output when the commit is unchanged.

Repository content is treated as untrusted: CodeAtlas only parses files, never executes them. Git hooks are disabled, symlinks are skipped, path inputs are validated, and oversized files are ignored.

## Development and validation

Run the project checks locally:

```bash
cd backend && source .venv/bin/activate && python -m pytest -q
cd frontend && npm run typecheck && npm run build
```

## Current static-analysis limitations

CodeAtlas is intentionally deterministic and syntax-driven rather than compiler-grade. It labels graph edges as `confirmed`, `inferred`, `external`, or `unresolved` and does not infer links when the target cannot be resolved confidently.

Known limitations include:

- No deep type inference beyond declared types
- Overload resolution by arity only
- Limited handling of chained call receivers
- Python analysis via the standard-library AST
- No evaluation of dynamic dispatch, reflection, or runtime import behavior
- Partial handling of Android navigation and dependency-injection patterns
- Simplified matching for Kotlin extension functions and import aliases
- Repository role labels that may be inferred rather than fully semantic

These limits are documented in the code paths and are intentionally explicit to preserve clarity and trust in the generated graph.

## Troubleshooting

| Symptom | Fix |
|---|---|
| GitHub OAuth is not configured | Set `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` in `.env` and restart the backend |
| Redirect URI mismatch | Use exactly `http://localhost:8000/auth/github/callback` |
| Invalid state or login loop | Use `http://localhost:5173` consistently and clear cookies |
| Private repos are missing | Reconnect with GitHub and approve the app for the relevant organization |
| Backend is unreachable | Start the API on port 8000 |
| `Attribute "app" not found` | Use `uvicorn app.main:create_app --factory` |
| Clone or checkout fails | Ensure `git` is installed and the branch exists |
| Empty graph | The repository may have no relevant Python, Kotlin, or Java sources outside ignored directories |
| Reset everything | Stop the servers and remove `.codeatlas-data/` |

## Project structure

```text
backend/          Python API and analysis engine
frontend/         React UI and visualization layer
README.md         Project overview and setup guide
dev.sh            Local development bootstrap
```

## Security and trust model

- Repository content is parsed but never executed.
- OAuth tokens are stored encrypted on the server.
- Only configured, validated repository paths are processed.
- Local caches under `.codeatlas-data/` are reused when possible to reduce redundant analysis.

## License

This project is distributed under the repository's existing license terms. See the repository root for the applicable license file.
