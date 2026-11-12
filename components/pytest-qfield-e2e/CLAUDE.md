# CLAUDE.md: pytest-qfield-e2e

Component-specific guidance for `pytest-qfield-e2e`. Workspace-wide conventions are in the root `CLAUDE.md`.

## App mode

This component drives the stock QField AppImage instead of rendering QML on QGIS. It must never import PyQt or qgis. Run its tests through its own config so its `addopts` disable the QGIS based plugins:

```bash
uv run --package pytest-qfield-e2e --all-extras --all-groups pytest -m "not qfieldcloud" components/pytest-qfield-e2e/test
```

The tests share the QField test project in `components/pytest-qfield/test/data`.

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
- QFieldCloud: the worker hands its own `/tmp` path to the sibling container, `TMP_DIRECTORY` must stay `/tmp`. The upstream `STORAGES` endpoint carries the object storage API port, the stack rewrites it. A failed job can exit 0, read the job `feedback`. Upstream publishes every port on all interfaces, the generated services override binds them to localhost and only the storage API to `storage_host`.
