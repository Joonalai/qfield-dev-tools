# pytest-qfield-e2e

Run plugin and end-to-end tests against a real QField app. Where `pytest-qfield`
renders plugin QML on QGIS with stubs, this plugin starts the stock QField release
AppImage through [qfield-driver](https://github.com/Joonalai/qfield-dev-tools/tree/main/components/qfield-driver)
and drives it like a user: real taps, real typing, real forms, real projects. The
`cloud` extra adds a local QFieldCloud for end-to-end tests with several devices
syncing through it.

Status: experimental. Linux x64 only. The system requirements are those of
[qfield-driver](https://github.com/Joonalai/qfield-dev-tools/tree/main/components/qfield-driver#requirements).

## Fixtures

| Fixture | Scope | What |
| --- | --- | --- |
| `qfield_app_version` | session | Release under test, from `--qfield-version`, env `QFIELD_VERSION`, ini `qfield_version`, default `4.2.9`. `latest` resolves the newest release. |
| `qfield_app_binary` | session | QField of your own from `--qfield-app-binary`, env `QFIELD_APP_BINARY` or ini `qfield_app_binary`: an AppRun, an AppImage (runs through FUSE) or a build. Otherwise the extracted `AppRun`, fetched once by [qfield-fetch](https://github.com/Joonalai/qfield-dev-tools/tree/main/components/qfield-fetch) into `~/.cache/qfield-fetch` (env `QFIELD_FETCH_CACHE_DIR`, ini `qfield_fetch_cache_dir`). |
| `qfield_app_plugins` | function | App plugins installed in every started app, `{uuid: directory}`. Empty by default. |
| `qfield_app_settings` | function | QField settings written before start, `{"myplugin/interval": 50}`. For values a plugin reads once on load. |
| `qfield_app_factory` | function | `start(name="device", app_plugins=None)` starts another app with its own profile. |
| `qfield_app` | function | One running app, a `qfield_driver.app.QFieldApp`. |

With the `cloud` extra (`pytest-qfield-e2e[cloud]`):

| Fixture | Scope | What |
| --- | --- | --- |
| `qfieldcloud_ref` | session | QFieldCloud release: `hosted` (default), `latest` or a tag. `--qfieldcloud-ref`, env `QFIELDCLOUD_REF`, ini `qfieldcloud_ref`. With a checkout of your own (`--qfieldcloud-source-dir`, env `QFIELDCLOUD_SOURCE_DIR`, ini `qfieldcloud_source_dir`) it is `local-<directory>`, and the stack writes its `.env` and compose overrides into that checkout. |
| `qfieldcloud_stack` | session | The official compose stack at that release, built and started once, then reused across sessions. `--qfieldcloud-down` removes it after the session. Ini `qfieldcloud_https_port` changes its HTTPS port. |
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

`qfield_app.eval`, `host_plugin`, the `actions` helpers and positioning are
documented in [qfield-driver](https://github.com/Joonalai/qfield-dev-tools/tree/main/components/qfield-driver#usage).
`qfield_app_plugins` installs the plugin under test as a real app plugin instead,
a black box.

## QFieldCloud recipe

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

How the stack runs, and `qfield-driver-cloud` to start or remove it ahead of
a run, are in [qfield-driver](https://github.com/Joonalai/qfield-dev-tools/tree/main/components/qfield-driver#qfieldcloud).

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
  rely on a fresh profile. Reused devices log to the session's `qfield-devices`
  temporary directory instead of `tmp_path`.
- `pytest-xdist` works, every device has its own display and ports. Workers
  share one QFieldCloud stack and get their own users, `alice` becomes
  `alice_gw1` through `worker_username`, which the cloud fixtures apply.
  `--qfieldcloud-down` removes the stack once all workers are done.
