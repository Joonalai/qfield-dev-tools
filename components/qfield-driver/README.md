# qfield-driver

Drive a real QField app from Python. It starts the stock QField release AppImage and
uses it like a user: real taps, real typing, real forms, real projects. The `cloud`
extra adds a local QFieldCloud, for several devices syncing through it.

The driver has no pytest dependency. [pytest-qfield-e2e](https://github.com/Joonalai/qfield-dev-tools/tree/main/components/pytest-qfield-e2e)
wraps it in fixtures, and [qfield-mcp](https://github.com/Joonalai/qfield-dev-tools/tree/main/components/qfield-mcp)
lets AI agents drive it.

Status: experimental. Linux x64 only.

## How it works

- QField AppImages are downloaded and extracted once by [qfield-fetch](https://github.com/Joonalai/qfield-dev-tools/tree/main/components/qfield-fetch).
- QField runs on a private Xvfb with an isolated `HOME`, so it never touches your
  own QField profile or running instances. Cameras, when the machine has any, are
  hidden with a mount namespace (`unshare`). Telemetry is off.
- A small app plugin, the driver, is installed into that profile. It polls a localhost
  bridge (random token in the path) and runs JS function bodies sent from Python.
  Results come back JSON-decoded.
- Taps and keys are XTEST events on the private display, so they go through QField's
  normal input handling. Non-ASCII text such as `ä` is typed too.
- GNSS fixes come from a fake NMEA receiver that QField connects to over TCP.

No custom QField build is needed, the driver runs the binary users run.

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

On GitHub, the [setup-qfield-e2e](https://github.com/Joonalai/qfield-dev-tools/tree/main/.github/actions/setup-qfield-e2e)
action installs these on an Ubuntu runner and caches the AppImages.

## Usage

```bash
pip install qfield-driver          # or qfield-driver[cloud]
```

```python
from pathlib import Path

from qfield_fetch import appimage
from qfield_driver import actions
from qfield_driver.app import QFieldApp

with QFieldApp(appimage("4.2.9"), Path("/tmp/device/home")) as app:
    app.host_plugin(Path("my_plugin/main.qml"))
    actions.open_project(app, Path("project/project.qgs"))
    actions.tap_object(app, "pluginButton")
    actions.wait_for_message(app, "Plugin button clicked!")
    print(app.eval("return plugin.clicks"))
```

`QFieldApp(app_run, home, app_plugins=None, settings=None, ...)` starts on enter and
stops on exit. `app_run` is an extracted `AppRun`, an AppImage (runs through FUSE) or a
build, `local_app(path)` checks it. `home` is created and becomes QField's profile, the
log goes next to it as `<home>.log`. `settings` are QField settings written before the
start, `{"myplugin/interval": 50}`, for values a plugin reads once on load.

`QFieldApp.eval(code)` runs a JS function body inside QField. The body sees `iface`,
`find` (`iface.findItemByObjectName`), `findItem` (scene search by objectName, also
in popups and plugin toolbars), `walk`, `walkAll`, `scene`, `state` (kept between
calls), `plugin` (the hosted plugin root), `qgisProject`, `layerObserver`,
`pluginManager`, `settings`, `platformUtilities`, `messageLogModel`,
`featureHistory`, `flatLayerTree`, `trackingModel`, `LayerUtils`, `GeometryUtils`,
`FeatureUtils`, `StringUtils` and `Theme`. `wait(code)` polls it until truthy.

Other methods: `click`, `long_press`, `drag`, `type_text`, `key`, `screenshot`,
`log_text`, `wait_for_log`, `reset` (back to a clean state for reuse) and
`diagnose` (message log, log tail and a screenshot of a failure).

### Loading the plugin under test

- `app.host_plugin(main_qml)` creates the plugin the way QField's plugin manager
  does, but keeps its root reachable as `plugin`, so callers can inspect plugin
  state. `reload_plugin()` loads it again with your edits. Unknown names in the
  plugin resolve through the driver's context, which only has `_pqf` prefixed members.
- `QFieldApp(app_plugins={uuid: directory})` installs it as a real app plugin
  instead, a black box.
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

Differences from QGIS based stubs to expect: a NULL integer attribute reads as `0`
in QField JS, `ExpressionEvaluator` hands back text, plugin popups animate open and
closed so wait for `visible` instead of asserting it, and the message log lists
newest first.

Item names follow QField 4.2. Recheck them on a version bump, QField 4.3 renamed
its QML sources.

### Positioning

```python
app.set_position(389870.0, 6678167.0)  # project CRS
app.wait_for_position(389870.0, 6678167.0)
app.lose_position()
```

## QFieldCloud

With the `cloud` extra. QFieldCloud releases often and only the newest release is
maintained. `QFieldCloudStack` runs the official compose stack of one release, and
`resolve_ref("hosted")` follows app.qfield.cloud, so a run matches what field devices
sync against. Each release gets its own compose project, images and volumes, and its
checkout lives in the qfield-fetch cache.

```python
from qfield_fetch import default_cache_dir
from qfield_driver.cloud.client import QFieldCloudClient
from qfield_driver.cloud.stack import QFieldCloudStack, resolve_ref

stack = QFieldCloudStack(resolve_ref("hosted"), default_cache_dir())
stack.up()  # builds once, then reuses the running stack
admin = QFieldCloudClient(stack.url, *stack.admin, verify=stack.ca_certificate)
project_id = admin.create_project("survey")
admin.upload(project_id, Path("project"))
admin.package(project_id)
```

- `stack.ensure_user(name, password)` creates a user. The client covers projects,
  collaborators, files, jobs and deltas, with `wait_for_jobs` and `wait_for_deltas`.
- `QFieldCloudStack.local(checkout, cache_dir)` runs a QFieldCloud checkout of your own.
  It writes its `.env.<project>` and compose overrides into that checkout.
- The stack runs on `https://localhost:8543`. Clients verify TLS against the stack's
  own mkcert authority, `stack.ca_certificate`. QField accepts it, since it ignores TLS
  errors on hosts outside `.qfield.cloud`.
- Ports are bound to localhost. Only the object storage API also listens on the host's
  LAN address, where the containers reach it.
- The admin is `admin`/`admin123`, so keep it a disposable test stack.
- When a package job fails with exit code 0, read the job `feedback` through
  `client.jobs(project_id)`. The worker log alone is misleading.

### Command line

```bash
qfdc ref                                # what `hosted` resolves to
qfdc ref --check v26.30                 # exit 1 when the pinned tag is not hosted
qfdc up --ref latest                    # build and start
qfdc up --source-dir ~/src/QFieldCloud  # a checkout of your own
qfdc down
qfdc prune                              # remove the stacks of older releases
```

`qfdc` is short for `qfield-driver-cloud`. `up` and `down` take `--port-offset`, see
below.

### Several stacks at once

Runs on one stack share its admin token, and one run's login ends the other's session
(`Token has expired`). Give each parallel run, such as each git worktree, a stack of
its own with a port offset:

```python
stack = QFieldCloudStack.with_offset(resolve_ref("hosted"), default_cache_dir(), 10)
```

- Every port moves up by the offset and the compose project gets the suffix `-10`.
  Explicit ports and `name` still win, offset 0 is the plain stack. `local()` takes an
  `offset` too, and the command line `--port-offset` or `QFIELDCLOUD_PORT_OFFSET`.
- Use multiples of 10 up to 50. Other offsets can collide: at offset 0 the stack uses
  the host ports 8109, 8113, 8180 (and 8182 to 8184 for the mail test server), 8432
  and 8543.
- Each offset builds its own images, so its first start is a long build and takes
  extra GB.
- Stacks of one release share the checkout, each with its own `.env.<project>` and
  services override. `qfdc prune` removes the offset stacks of an old release too.

### In a container

The stack's containers are siblings started by the host's engine, which resolves every
bind mount on the host. When the tests run in a container:

- Mount the engine socket, the repository and the qfield-fetch cache at their host paths.
- Set `DOCKER_HOST=unix://<host socket path>`.

Without `DOCKER_HOST`, `container_socket()` warns inside a container. When the worker
cannot reach the engine, `up()` raises an error naming the socket, instead of package
jobs staying pending. An example Containerfile, entrypoint, compose file and Makefile
target are in [docs/container.md](https://github.com/Joonalai/qfield-dev-tools/blob/main/components/qfield-driver/docs/container.md).

### Changes to the upstream stack

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
- Images are tagged with the checkout's version from `git describe`, `v26.30` or
  `v26.30-3-gebfdcab`, and built again when it changes. Uncommitted edits in a
  checkout of your own add a hash of the diff. Older version tags are removed.
