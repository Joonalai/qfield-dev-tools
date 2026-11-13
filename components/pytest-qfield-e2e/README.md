# pytest-qfield-e2e

Run plugin and end-to-end tests against a real QField app. Where `pytest-qfield`
renders plugin QML on QGIS with stubs, this plugin starts the stock QField release
AppImage and drives it like a user: real taps, real typing, real forms, real projects.
The `cloud` extra adds a local QFieldCloud for end-to-end tests with several devices
syncing through it.

Status: experimental. Linux x64 only.

## How it works

- Downloads and extracts a QField release AppImage once into a cache.
- Starts QField on a private Xvfb with an isolated `HOME`, so it never touches your
  own QField profile or running instances. Cameras, when the machine has any, are
  hidden with a mount namespace (`unshare`). Telemetry is off.
- Installs a small test-only app plugin, the driver. It polls a localhost bridge
  (random token in the path) and runs JS function bodies the test sends. Results
  come back JSON-decoded.
- Taps and keys are XTEST events on the private display, so they go through
  QField's normal input handling. Non-ASCII text such as `ä` is typed too.
- GNSS fixes come from a fake NMEA receiver that QField connects to over TCP.

No custom QField build is needed, the test runs the binary users run.

## Requirements

- `Xvfb`
- The system libraries the AppImage does not bundle. On Ubuntu 24.04:
  `xvfb ca-certificates libfontconfig1 libegl1 libopengl0 libgl1 libglx-mesa0
  libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1
  libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-xkb1
  libdbus-1-3`
- On machines with cameras, util-linux `unshare` with unprivileged user namespaces.
  Without `/dev/video*` QField starts directly, as in containers and CI.
- For QFieldCloud: docker or rootless podman with `docker compose`, and `git`

## Fixtures

| Fixture | Scope | What |
| --- | --- | --- |
| `qfield_app_version` | session | Release under test, from `--qfield-app-version`, env `QFIELD_APP_VERSION`, ini `qfield_app_version`, default `4.2.9`. `latest` resolves the newest release. |
| `qfield_app_binary` | session | Extracted `AppRun`, cached under `~/.cache/pytest-qfield-e2e` (env `QFIELD_APP_CACHE_DIR`). |
| `qfield_app_plugins` | function | App plugins installed in every started app, `{uuid: directory}`. Empty by default. |
| `qfield_app_settings` | function | QField settings written before start, `{"myplugin/interval": 50}`. For values a plugin reads once on load. |
| `qfield_app_factory` | function | `start(name="device", app_plugins=None)` starts another app with its own profile. |
| `qfield_app` | function | One running app. |

With the `cloud` extra (`pytest-qfield-e2e[cloud]`):

| Fixture | Scope | What |
| --- | --- | --- |
| `qfieldcloud_ref` | session | QFieldCloud release: `hosted` (default), `latest` or a tag. `--qfieldcloud-ref`, env `QFIELDCLOUD_REF`, ini `qfieldcloud_ref`. |
| `qfieldcloud_stack` | session | The official compose stack at that release, built and started once, then reused across sessions. `--qfieldcloud-down` removes it after the session. |
| `qfieldcloud_admin` | session | REST client logged in as the admin. |
| `qfieldcloud_user` | session | `user(name, password=...)` creates a user once and returns its client. |
| `qfieldcloud_project` | function | `create(directory, name=None, collaborators=())` uploads and packages a project, deleted after the test. |
| `qfieldcloud_device` | function | `start(project_id, username, ...)` starts QField, logs in, downloads and opens the project. |

## Writing tests

```python
from qfield_driver import actions


def test_button_logs(qfield_app, tmp_path):
    qfield_app.host_plugin(PLUGIN_DIR / "main.qml")
    actions.open_project(qfield_app, PROJECT_FILE)

    actions.tap_object(qfield_app, "pluginButton")

    actions.wait_for_message(qfield_app, "Plugin button clicked!")
    assert qfield_app.eval("return plugin.clicks") == 1
```

`QFieldApp.eval(code)` runs a JS function body inside QField. The body sees `iface`,
`find` (`iface.findItemByObjectName`), `findItem` (scene search by objectName, also
in popups and plugin toolbars), `walk`, `walkAll`, `scene`, `state` (kept between
calls), `plugin` (the hosted plugin root), `qgisProject`, `layerObserver`,
`pluginManager`, `settings`, `platformUtilities`, `messageLogModel`,
`featureHistory`, `flatLayerTree`, `trackingModel`, `LayerUtils`, `GeometryUtils`,
`FeatureUtils`, `StringUtils` and `Theme`.

### Loading the plugin under test

- `qfield_app.host_plugin(main_qml)` creates the plugin the way QField's plugin
  manager does, but keeps its root reachable as `plugin`, so tests can assert on
  plugin state. Unknown names in the plugin resolve through the driver's context,
  which only has `_pqf` prefixed members.
- `qfield_app_plugins` installs it as a real app plugin instead, a black box.
- Project plugins come with the project, `actions.open_project(app, path,
  grant_plugin=True)` answers QField's permission prompt.

### Actions

`qfield_driver.actions` has user level helpers built on QField's own item
names: `tap_object`, `tap_text`, `tap_icon`, `type_into`, `expand_drawer`,
`open_project`, `frame_map`, `tap_map`, `long_press_map`, `digitize_point`,
`open_feature_form`, `edit_in_form`, `set_field`, `choose_option`, `toggle_switch`,
`tick_item`, `search_and_tick`, `attach_photo`, `open_related`, `save_form`,
`wait_visible`, `wait_for_text` (toasts), `frame_and_tap`, `scan_code` (QField's
code reader), `features`, `geometries`, `feature_count`, `add_feature`,
`change_geometry`, `evaluate_expression`, `import_js` (call a plugin's JS module),
`highlighted_wkt`, `log_messages`, `wait_for_message`, and the cloud steps `login`,
`download_project`, `push` and `synchronize`. `qfield_driver.wkt` has `length`
and `interpolate`, which QField does not expose to QML.

Differences from stubs to expect: a NULL integer attribute reads as `0` in QField JS,
`ExpressionEvaluator` hands back text, plugin popups animate open and closed so wait
for `visible` instead of asserting it, and the message log lists newest first.

Item names follow QField 4.2. Recheck them on a version bump, QField 4.3 renamed
its QML sources.

### Positioning

```python
qfield_app.set_position(389870.0, 6678167.0)  # project CRS
qfield_app.wait_for_position(389870.0, 6678167.0)
qfield_app.lose_position()
```

## QFieldCloud recipe

QFieldCloud releases often and only the newest release is maintained. The stack
follows app.qfield.cloud by default, so a test run always matches what field
devices sync against. Each release gets its own compose project, images and
volumes.

```bash
python -m qfield_driver.cloud ref               # what `hosted` resolves to
python -m qfield_driver.cloud up --ref latest   # build and start ahead of a run
python -m qfield_driver.cloud prune             # remove stacks of older releases
python -m qfield_driver.cloud down
```

```python
def test_edit_reaches_cloud(
    project_dir,
    qfieldcloud_user,
    qfieldcloud_project,
    qfieldcloud_device,
    qfieldcloud_admin,
):
    qfieldcloud_user("surveyor")
    project_id = qfieldcloud_project(project_dir, collaborators=("surveyor",))
    app = qfieldcloud_device(project_id, "surveyor")

    actions.edit_in_form(app, "points", "fid = 1", "text_field", "new")
    pushed = actions.push(app, project_id)

    deltas = qfieldcloud_admin.wait_for_deltas(project_id, pushed)
    assert {d["status"] for d in deltas} == {"STATUS_APPLIED"}
```

The stack runs on `https://localhost:8543` with a self-signed certificate. QField
accepts it, it ignores TLS errors on hosts outside `.qfield.cloud`. Overrides
applied to the upstream compose files:

- Logging driver `json-file`, podman rejects the upstream `tag` option.
- The worker mounts the docker or podman socket found on the host.
- nginx gets the runtime's DNS resolver, docker and podman differ.
- `TMP_DIRECTORY` stays `/tmp`, the worker hands its own temp path to the sibling
  QGIS container.
- `ofelia` is disabled and host ports are moved off common defaults.
- Storage endpoints point at this machine's address and the published API port.
  The upstream default, docker's bridge `172.17.0.1`, does not exist under podman.
- Images to build are read from the release's compose files, so a new worker image
  (`qgis4` in v26.30) is built without a code change.

When a package job fails with exit code 0, read the job `feedback` through
`qfieldcloud_admin.jobs(project_id)`, the worker log alone is misleading.

## Running

```bash
pytest -p no:pytest-qfield -p no:pytest_qgis -p no:pytest-qt test_app
```

The QGIS based plugins are not needed for app tests and importing Qt in the test
process is pointless, so disable them for app test runs.

Each test starts its own QField, about 5 s on a laptop. Device logs are in
`tmp_path/<device>.log`, and `qfield_app.screenshot(path)` saves the window.

A failing test gets a section per device in its report: the newest message log
lines, the log tail and a screenshot path. No screenshot is taken while a camera
view is open.

### Faster runs

- `--qfield-app-reuse` (ini `qfield_app_reuse = true`) keeps each device running
  and resets it between tests: plugin unhosted, popups closed, project cleared,
  position lost, `state` emptied. A device is started again when the plugins or
  settings differ. Settings a test changes stay, so keep it off for tests that
  rely on a fresh profile.
- `pytest-xdist` works, every device has its own display and ports. Workers
  share one QFieldCloud stack and get their own users, `alice` becomes
  `alice_gw1` through `worker_username`, which the cloud fixtures apply.
  `--qfieldcloud-down` removes the stack once all workers are done.
