# CLAUDE.md: qfield-driver

Component-specific guidance for `qfield-driver`. Workspace-wide conventions are in the root `CLAUDE.md`.

## Driver

This component drives the stock QField AppImage instead of rendering QML on QGIS. It must never import pytest, PyQt or qgis, `pytest-qfield-e2e` and `qfield-mcp` build on it. Its tests are unit tests of the display and the QFieldCloud stack:

```bash
uv run --package qfield-driver --all-extras --all-groups pytest components/qfield-driver/test
```

Behaviour against a real app is tested in `pytest-qfield-e2e`.

Gotchas learned against QField 4.2.9 and 4.3.8:

- Never start `qfield` directly or kill QField by name, the developer often has it open. `QFieldApp` isolates `HOME` and XDG dirs and stops only its own process groups.
- The camera button opens the host webcam under Xvfb unless `/dev/video*` is hidden, which `QFieldApp` does with `unshare`. Never screenshot camera views.
- Plugin QML errors go to QGIS' message log, not stdout. Read `messageLogModel` (newest first) or use `Qt.createComponent(path).errorString()`.
- A project plugin waits on a permission prompt, `open_project(..., grant_plugin=True)` answers it. Without it QField runs silently without the plugin.
- `iface.findItemByObjectName` misses plugin toolbar items and popups. The driver's `findItem` walks the scene and the hosted plugin's `data`, `children` and popup `contentItem`.
- Field editor loaders are named by the field alias, `attributeEditorLoader<alias>`.
- After typing in a ValueRelation search, wait about 1 s before tapping a row.
- A NULL integer attribute reads as `0` in QField JS, stubs return `null`.
- `ExpressionEvaluator.evaluate` returns text.
- Wait for `!cloudProjectsModel.isRefreshing` before a download, a list reply mid-download fails transfers.
- QFieldCloud: the worker hands its own `/tmp` path to the sibling container, `TMP_DIRECTORY` must stay `/tmp`. The upstream `STORAGES` endpoint carries the object storage API port, the stack rewrites it. A failed job can exit 0, read the job `feedback`. Upstream publishes every port on all interfaces, the generated services override binds them to localhost and only the storage API to `storage_host`. Built images keep their `<project>-<service>:latest` name, the worker starts siblings by it, and get a version tag from `source_version` that decides when to rebuild.
- Stacks of one ref (port offsets) share the checkout, so each project has its own `.env.<project>` and services override, and `compose()` passes `--project-name` and `--env-file`. Never write a shared `.env` or target a stack without them, the last writer would win. Prune finds projects through `docker compose ls`, not the checkout.
