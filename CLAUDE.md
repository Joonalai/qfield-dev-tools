# CLAUDE.md

Guidance for AI coding agents working in `qfield-dev-tools`. Each component's README covers its user-facing API; this file and the component-level `CLAUDE.md` files focus on gotchas and conventions that aren't obvious from reading the code.

## Agent skills

Shared skills live in `.agents/skills/`, managed by the [nlsfi agent-instructions template](https://github.com/nlsfi/agent-instructions-template) (`.copier-answers.agent-instructions.yml`). `.claude/skills` is a symlink to it so Claude Code discovers them; other agents should read the matching `SKILL.md` when its description fits the task.

- `nls-python` for any `.py` change and `nls-qgis` for PyQGIS code. `pyqgis-dev` to verify QGIS/PyQt API facts.
- `nls-security-review` and `nls-ai-housekeeping` only when explicitly asked.
- Never hand-edit `.agents/`; change the copier answers and run `copier update --trust --answers-file .copier-answers.agent-instructions.yml`. prek skips the folder.
- Where a skill conflicts with this file, this file wins:
  - Docstrings only where the code doesn't already say it (`nls-python` asks for one on every public function).
  - QField stubs mirror QField's API, so `QSettingsStub` stays `QSettings`-based despite `nls-qgis`'s `QgsSettings` rule. The `nls-qgis` plugin rules (settings, translations, `deactivate()` teardown) apply to QGIS plugins, not to pytest-qfield.

## Workspace layout

The repo is a uv workspace. Every directory under `components/` is a member; `pytest-qfield` is the first.

- Not all components can be installed at the same time, so the root `pyproject.toml` never depends on a component. Sync one at a time: `uv sync --package <component> --all-groups`. Plain `--package` drops the root's `dev`/`lint` groups.
- The root holds what all components share: the `dev` (pytest plugins) and `lint` groups, and the ruff and flake8 config. Package metadata, pytest config and semantic-release config live in each component's `pyproject.toml`.
- There is a single `uv.lock` for the whole workspace. Components with dependencies that can't be installed together must be declared in `[tool.uv] conflicts`.
- The `.venv` must be created with `uv venv --system-site-packages`, using the same Python as QGIS, so the system QGIS bindings are visible. The system PyQt6 lacks QML bindings, so a PyQt6 wheel matching the system Qt minor version is installed on top (see `.github/workflows/tests.yml`). `uv sync` removes that wheel; reinstall it after syncing if PyQt6 imports fail.

## Running tests and hooks

Always run pytest offscreen so no windows pop over the developer's work. `.env` in the repository root is loaded automatically by `pytest-dotenv`. Components may need extra flags; see their `CLAUDE.md`.

```bash
QT_QPA_PLATFORM=offscreen uv run --package <component> pytest components/<component>
```

Pre-commit checks (`mypy`, `ruff`, etc.) run via `prek`:

```bash
uv run prek run --all-files
```

Both must pass before committing. Fix root causes; don't bypass hooks.

## Linting

- Ruff runs with `select = ["ALL"]`. Global and per-path ignores live in the root `pyproject.toml`, each with a reason. Fix new findings rather than extending the ignore list.
- Use an inline `# noqa: <code>` only with a real reason, such as a Qt/PyQt API that dictates the signature, or a fix that would change a public API (e.g. making boolean flags keyword-only for `FBT`, or turning an `assert` into another exception type). Lint fixes must never be breaking changes.
- TODOs need an author: `# TODO(<github-handle>): ...`.
- Hook revisions in `.pre-commit-config.yaml` are frozen to commit SHAs. Update them with `uv run prek update --freeze`, and keep the mypy/ruff versions in sync with the `lint` group in `uv.lock`.
- `prek install` also installs the `commit-msg` hook, so gitlint checks every commit message against `.gitlint`: a conventional-commit title of at most 72 characters, lowercase after the colon.

## Code style and conventions

- Don't add docstrings, comments, or error messages for things the code already says. Comments should explain *why*, not *what*.
- Internal code has no compatibility promises: change it directly instead of adding shims or feature flags. Published public APIs (fixtures, `QFieldBot` methods, config options) do: keep them backwards compatible, and rename through a deprecation period, like `QFIELD_IMPORTS_DIR` → `QFIELD_SOURCE_DIR`.
