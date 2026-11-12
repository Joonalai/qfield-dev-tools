# qfield-mcp

MCP server that starts stock QField AppImages on private displays and lets an agent look at the screen, tap, type and run JavaScript inside QField. Built on `qfield-driver`, so it needs the same system packages: Linux x64, Xvfb and util-linux `unshare`.

```bash
claude mcp add qfield -- uv run --directory /path/to/qfield-dev-tools/components/qfield-mcp qfield-mcp
```

AppImages come from the [qfield-fetch](https://github.com/Joonalai/qfield-dev-tools/tree/main/components/qfield-fetch) cache, `~/.cache/qfield-fetch` unless `QFIELD_FETCH_CACHE_DIR` is set.

## Tools

- `start_device`, `stop_device`, `list_devices`: one QField per device name, with its own profile, display and fake GNSS receiver. `start_device` can host a plugin directory and open a project.
- `item_tree`: visible items with object names, texts and window positions.
- `tap`, `tap_map`, `frame_map`, `type_text`, `key`: real input events.
- `screenshot`: the window as PNG, refused while a camera view is open.
- `eval_js`: a JS function body run inside QField.
- `messages`, `log`: QField's message log and process output.
- `open_project`, `set_position`.
