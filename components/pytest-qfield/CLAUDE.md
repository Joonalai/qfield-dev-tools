# CLAUDE.md — pytest-qfield

Component-specific guidance for `pytest-qfield`. Workspace-wide conventions are in the root `CLAUDE.md`.

## Stub design philosophy

The QML-facing classes in `src/pytest_qfield/stub_interface/` are not generic Python wrappers — they're an **API contract** that mirrors what QField's QML can actually call in production. Two consequences:

- **Stubs are intentional whitelists.** `QgsGeometryStub` only re-exports `asWkt(int)` because that's what QField QML supports. Replacing it with raw `QgsGeometry` would let tests pass on methods (like `area()`) that aren't `Q_INVOKABLE` and would fail at runtime in QField. Add methods deliberately, not by reflex.
- **The friction of hand-rolling is the point.** Each new pyqtSlot/pyqtProperty is a deliberate "yes, QField supports this" decision. Don't introduce metaclasses or auto-mirror decorators that silently expand the surface.

If you find yourself wanting to use a real QGIS class instead of a stub, the test is: *does QField's QML actually expose this surface?* If yes (e.g., delegating `screenToCoordinate` to `QgsMapCanvas.mapSettings().mapToPixel()`), go for it. If no, keep the stub.

Stub slots mirror QField's C++ signatures, which QML calls positionally, so `FBT001`/`FBT002` are ignored in `stub_interface/` and tests calling those APIs are exempt from `FBT003`.

## Q_INVOKABLE vs Q_PROPERTY vs pyqtProperty

These three look interchangeable but aren't, and getting them wrong silently breaks one of the consumers. Cheat sheet:

| Mechanism | Callable from QML | Callable from `QObject.property()` | Accessible as Python `obj.x` (attribute) |
| --- | --- | --- | --- |
| `Q_INVOKABLE` method (C++) | yes, as function `obj.x()` | no | no — `obj.x` is the bound method |
| `Q_PROPERTY` (C++, e.g. on `QgsPoint`) | yes, as property `obj.x` | yes | **no** — `obj.x` is still the bound method |
| `pyqtProperty` (PyQt decorator) | yes, as property `obj.x` | yes | **yes** — installs a Python descriptor |

If a value needs to be readable from both QML (`pos.x`) and Python tests (`stub.x`), it **must** be a `pyqtProperty`. Replacing a `pyqtProperty`-based stub with a real `QgsPoint` / `QgsGeometry` will satisfy QML but break Python attribute access.

### pyqtProperty + mypy

The `@property.setter` form trips mypy with `[no-redef]` on the second decoration and `[method-assign]` on `self.foo = ...` inside methods. The accepted pattern in this codebase is to keep the decorator form and add localized ignores:

```python
@foo.setter  # type: ignore[no-redef]
def foo(self, value): ...


def clear(self):
    self.foo = None  # type: ignore[method-assign]
```

The functional `pyqtProperty(type, fget=..., fset=...)` form also works but reads worse — six ignores beat ten lines of helper methods.

## Fixture override patterns

Every stub fixture in `src/pytest_qfield/plugin.py` is overridable by redefining it in user `conftest.py`. Two categories with different wiring:

1. **Context-property stubs** (`qfield_iface`, `qgs_project_stub`, `qfield_theme_stub`, `qfield_string_utils_stub`, …): injected into the QML engine's root context by name. Overriding the fixture swaps the instance globally.
2. **Named-item stubs** (`qfield_positioning_stub`, `qfield_geometry_highlighter_stub`): auto-registered on the iface stub by the autouse `_attach_default_iface_stubs` fixture and located via `iface.findItemByObjectName(...)`. Override the same way.

When adding a new stub category, follow whichever pattern matches how QField QML actually looks the thing up.

## QField source dependency

The plugin loads QML from QField's source tree — there's no way around having a checkout. With `QFIELD_VERSION` (or `--qfield-version`, `qfield_version`) qfield-fetch clones that ref into its cache. A configured `QFIELD_SOURCE_DIR` wins over the version and must point at the QField checkout root (a trailing `src/qml/imports` or `src/gui/qml` is stripped; the layout is detected) and the checkout's tag must match the QField version you're testing against. `.env.example` in the repository root has the canonical variable name.

## Tests

Run from the repository root with `--qgis_disable_gui` (a `pytest-qgis` option) so QGIS doesn't open dialogs over the developer's work:

```bash
QT_QPA_PLATFORM=offscreen uv run --package pytest-qfield pytest --qgis_disable_gui components/pytest-qfield
```

The tests double as usage examples for the library's users, so test docstrings and explanatory comments are kept, despite `nls-python`'s no-comments-in-tests rule.

Visual tests use `qgis_show_map(timeout=0)`, which closes the map immediately. To inspect them, raise the timeout locally and run without `--qgis_disable_gui`, but never commit a non-zero timeout.

Visual tests in `test/visual/` run headless under `QT_QPA_PLATFORM=offscreen` like the rest — they're still tests, not interactive demos.
