# qfield-mcp

MCP server that starts stock QField AppImages on private displays and lets an agent look at the screen, tap, type and run JavaScript inside QField. Built on [qfield-driver](https://github.com/Joonalai/qfield-dev-tools/tree/main/components/qfield-driver).

## Requirements

- Linux x64 with Xvfb, the system libraries the QField AppImage does not bundle and util-linux
  `unshare`, see the [qfield-driver requirements](https://github.com/Joonalai/qfield-dev-tools/tree/main/components/qfield-driver#requirements)
- [uv](https://docs.astral.sh/uv/)
- For the cloud tools: docker or rootless podman with `docker compose`, and `git`

## Install

Run it with `uvx`, which installs the package into an isolated environment on first use:

```bash
claude mcp add qfield -- uvx qfield-mcp
```

- Pin a release with `uvx qfield-mcp@0.1.0`, update a cached one with `uvx qfield-mcp@latest`.
- `claude mcp add --scope project qfield -- uvx qfield-mcp` writes the server into the
  repository's `.mcp.json`, so everyone working on your plugin gets it.
- If uv picks a Python that the dependencies have no wheels for yet, add `--python 3.12` after
  `uvx`.

Other MCP clients take the same command:

```json
{
  "mcpServers": {
    "qfield": {"command": "uvx", "args": ["qfield-mcp"]}
  }
}
```

## Configuration

AppImages come from the [qfield-fetch](https://github.com/Joonalai/qfield-dev-tools/tree/main/components/qfield-fetch) cache, `~/.cache/qfield-fetch` unless `QFIELD_FETCH_CACHE_DIR` is set.
The first `start_device` of a release downloads it. These variables of the server's environment
apply when a tool call names no version or ref:

| Variable | What |
| --- | --- |
| `QFIELD_APP_BINARY` | An AppRun, an AppImage or a build of your own instead of release 4.2.9 |
| `QFIELDCLOUD_SOURCE_DIR` | A QFieldCloud checkout of your own for `cloud_up` instead of the hosted release |

```bash
claude mcp add qfield -e QFIELD_APP_BINARY=/path/to/AppRun -- uvx qfield-mcp
```

## Tools

- `start_device`, `stop_device`, `list_devices`: one QField per device name, with its own profile, display and fake GNSS receiver. `start_device` can host a plugin directory and open a project. `reload_plugin` loads the hosted plugin again with your edits.
- `find_items`, `item_tree`: visible items with object names, texts, `[clickable]` and window positions. Both can list only clickable items.
- `wait_for`: until a JS body is truthy, or a text appears or disappears.
- `tap`, `tap_map`, `frame_map`, `type_text`, `key`: real input events.
- `screenshot`: the window or one item as PNG, optionally scaled down. Refused while a camera view is open.
- `eval_js`: a JS function body run inside QField.
- `messages`, `log`: QField's message log and process output.
- `open_project`, `set_position`, `features`, `open_feature_form`, `set_field`, `save_form`, `close_feature_form`.
- `cloud_up`, `cloud_login`, `cloud_download`, `cloud_synchronize`: a local QFieldCloud and devices synced with it.

Calls to one device run one at a time. Devices stop when the server exits, and a server that was killed has its devices stopped by the next server start.

## Development

To run the server from a checkout of [qfield-dev-tools](https://github.com/Joonalai/qfield-dev-tools),
see [DEVELOPMENT.md](https://github.com/Joonalai/qfield-dev-tools/blob/main/DEVELOPMENT.md).
