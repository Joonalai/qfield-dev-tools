# Development

How to set up, test and release qfield-dev-tools. Each component's README covers its user-facing
API, and `CLAUDE.md` files hold the gotchas for AI agents.

## Workspace

A uv workspace with one member per directory under `components/`:

| Component | What | Depends on |
| --- | --- | --- |
| [qfield-fetch](components/qfield-fetch/README.md) | Downloads QField AppImages and QField and QFieldCloud sources into one cache | |
| [pytest-qfield](components/pytest-qfield/README.md) | Renders plugin QML on QGIS with stubs | qfield-fetch |
| [qfield-driver](components/qfield-driver/README.md) | Drives a real QField app from Python, `cloud` extra for a local QFieldCloud | qfield-fetch |
| [pytest-qfield-e2e](components/pytest-qfield-e2e/README.md) | Pytest fixtures on the driver | qfield-driver, qfield-fetch |
| [qfield-mcp](components/qfield-mcp/README.md) | MCP server on the driver | qfield-driver[cloud], qfield-fetch |

- The root `pyproject.toml` never depends on a component, since not all of them install together.
  It holds the shared `dev` and `lint` groups and the ruff and flake8 config.
- One `uv.lock` for the whole workspace.

## Setup

```bash
uv venv --system-site-packages --python /usr/bin/python3   # the Python QGIS uses
uv sync --package <component> --all-groups                  # add --all-extras for driver, e2e and mcp
```

- Sync one component at a time. Plain `--package` drops the root's `dev` and `lint` groups.
- pytest-qfield needs a PyQt6 wheel with QML bindings that matches the system Qt minor version.
  `uv sync` removes it, so install it again after every sync:

  ```bash
  QT_MINOR=$(/usr/bin/python3 -c "from PyQt6.QtCore import QT_VERSION_STR; print(QT_VERSION_STR.rsplit('.', 1)[0])")
  uv pip install "PyQt6==${QT_MINOR}.*"
  ```

- Copy `.env.example` to `.env`. pytest loads it through `pytest-dotenv`.

| Variable | Used by | What |
| --- | --- | --- |
| `QFIELD_VERSION` | pytest-qfield, e2e | QField release or git ref. Its source or AppImage is fetched once. |
| `QFIELD_SOURCE_DIR` | pytest-qfield | A QField checkout of your own, wins over the version |
| `QFIELD_APP_BINARY` | e2e, mcp | A QField AppRun, AppImage or build of your own |
| `QFIELDCLOUD_SOURCE_DIR` | e2e, mcp | A QFieldCloud checkout of your own |
| `QFIELD_FETCH_CACHE_DIR` | all | Cache instead of `~/.cache/qfield-fetch` |

- App tests (driver, e2e, mcp) need Xvfb and the system libraries listed in the
  [qfield-driver requirements](components/qfield-driver/README.md#requirements). Cloud tests also
  need docker or rootless podman with `docker compose`.

## Make

The `Makefile` wraps the commands below. `make` lists the targets.

```bash
make venv            # .venv on the system Python
make test            # every suite except the cloud tests, each synced first
make test-e2e ARGS="-k reuse -x"
make test-cloud      # slow, builds a local QFieldCloud
make lint
```

Each test target syncs its component into the shared `.venv` first, `test-qfield` also adds the
PyQt6 wheel. `SYSTEM_PYTHON` (default `/usr/bin/python3`) picks the Python QGIS uses.

## Tests

Always run offscreen so no windows open over your work. From the repository root:

```bash
export QT_QPA_PLATFORM=offscreen

uv run --package qfield-fetch pytest components/qfield-fetch
uv run --no-sync --package pytest-qfield pytest --qgis_disable_gui components/pytest-qfield
uv run --package qfield-driver --all-extras --all-groups pytest components/qfield-driver/test
uv run --package pytest-qfield-e2e --all-extras --all-groups pytest -m "not qfieldcloud" components/pytest-qfield-e2e/test
uv run --package qfield-mcp --all-extras --all-groups pytest components/qfield-mcp/test
```

- `--no-sync` keeps the PyQt6 wheel for pytest-qfield.
- The app components' `addopts` disable the QGIS based plugins, they never import Qt.
- Cloud tests build and start a local QFieldCloud. They are slow, run them on purpose:
  `uv run --package pytest-qfield-e2e --all-extras --all-groups pytest -m qfieldcloud --qfieldcloud-down components/pytest-qfield-e2e/test`
- e2e and mcp tests share the QField test project in `components/pytest-qfield/test/data`.

Command line helpers, after syncing the component:

- `qff` (alias of `qfield-fetch`): `qff appimage 4.2.9`, `qff source 4.2.9`, `qff list`, `qff remove source v4.2.9`
- `qfdc` (alias of `qfield-driver-cloud`): `qfdc ref`, `qfdc up`, `qfdc prune`, `qfdc down`

Run qfield-mcp from the checkout, `--no-sync` keeps the server from syncing the shared `.venv`:

```bash
make sync-qfield-mcp
claude mcp add qfield -- uv run --no-sync --directory /path/to/qfield-dev-tools/components/qfield-mcp qfield-mcp
```

## Safety

- Never start `qfield` directly or kill QField processes by name, you may have QField open.
  The driver isolates `HOME` and stops only its own process groups.
- The local QFieldCloud admin is `admin`/`admin123`. Keep the stack disposable. Its ports bind to
  localhost, only the object storage API also listens on the LAN address.

## Hooks

Checks run through [prek](https://github.com/j178/prek):

```bash
uv run prek install              # also installs the commit-msg hook (gitlint)
uv run prek run --all-files
```

- Hooks: pre-commit-hooks, mypy, ruff, flake8, license headers, XML normalization, gitlint and
  actionlint. `.agents/` is skipped.
- Revisions are frozen to commit SHAs. Update them with `uv run prek update --freeze`, and keep
  mypy and ruff in sync with the `lint` group in `uv.lock`.
- actionlint checks `run` scripts with shellcheck only when `shellcheck` is on `PATH`. CI has it.
- Ruff runs with `select = ["ALL"]`. Fix findings instead of extending the ignore list.

## Commits

gitlint checks every commit message:

- Conventional commits: `chore`, `ci`, `docs`, `feat`, `fix`, `perf`, `refactor`, `style`, `test`
- Title at most 72 characters, lowercase after the colon, no `WIP`

Scopes tie a commit to a component even when it touches no files of it:

| Component | Scope | Tag |
| --- | --- | --- |
| qfield-fetch | `fetch` | `qfield-fetch-v{version}` |
| pytest-qfield | none | `v{version}` |
| qfield-driver | `driver` | `qfield-driver-v{version}` |
| pytest-qfield-e2e | `e2e` | `pytest-qfield-e2e-v{version}` |
| qfield-mcp | `mcp` | `qfield-mcp-v{version}` |

## Releases

- Each component releases on its own with python-semantic-release's `conventional-monorepo` parser,
  configured in the component's `pyproject.toml`.
- A commit counts for a component when it changes files in its directory or its scope matches.
  A `feat` or `fix` commit that touches several components releases each of them, so keep
  releasable commits to one component.
- Only `feat` (minor), `fix` and `build` (patch) release. Use `chore`, `ci` or `docs` for root-only
  changes.
- Merge pull requests with rebase merge, not squash, so each commit keeps its component.
- `.github/workflows/release.yml` runs on `main` and releases in dependency order: qfield-fetch,
  pytest-qfield, qfield-driver, pytest-qfield-e2e, qfield-mcp. Add a step for a new component.
- Each release is published to PyPI right away with trusted publishing (environment `pypi`). A new
  package needs a pending publisher for `release.yml` first. PyPI consumes a matching pending
  publisher on the run's first upload, whichever package it is, so add it right before merging the
  pull request that first releases the package, and make sure that run releases nothing else.
- After a release, `scripts/bump_dependents.py` raises the requirement in each dependent and commits
  `build(deps): require <component> >=<version> in <dependent>`, which releases the dependent too.

## CI

| Workflow | What |
| --- | --- |
| `tests.yml` | qfield-fetch, and pytest-qfield in `qgis/qgis` containers across QGIS and QField versions |
| `e2e-tests.yml` | Driver, e2e and mcp tests against QField 4.2.9 and `latest`, also nightly |
| `cloud-tests.yml` | Cloud tests against the hosted QFieldCloud release. On pull requests that change cloud code, nightly and on manual dispatch |
| `prek.yml` | All hooks |
| `release.yml` | Releases, see above |

The reusable actions are used by other repositories, so treat their inputs as a public API:

- `.github/actions/setup-pytest-qfield`: virtualenv with system QGIS, the project install and the matching PyQt6 in a `qgis/qgis` container
- `.github/actions/setup-qfield-e2e`: Xvfb, system libraries, uv and the AppImage cache on an Ubuntu runner
