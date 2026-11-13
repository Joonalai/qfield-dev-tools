# CLAUDE.md: pytest-qfield-e2e

Component-specific guidance for `pytest-qfield-e2e`. Workspace-wide conventions are in the root `CLAUDE.md`.

## App mode

This component wraps `qfield-driver` in pytest fixtures. It must never import PyQt or qgis. Run its tests through its own config so its `addopts` disable the QGIS based plugins:

```bash
uv run --package pytest-qfield-e2e --all-extras --all-groups pytest -m "not qfieldcloud" components/pytest-qfield-e2e/test
```

The tests share the QField test project in `components/pytest-qfield/test/data`. QField gotchas are in `components/qfield-driver/CLAUDE.md`, read them before changing tests or the driver.
