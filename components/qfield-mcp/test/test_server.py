# Copyright (C) 2026 qfield-dev-tools Contributors.
#
#
# This file is part of qfield-dev-tools.
#
# qfield-dev-tools is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# qfield-dev-tools is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with qfield-dev-tools.  If not, see <https://www.gnu.org/licenses/>.

import asyncio
import json
import shutil
import subprocess
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from qfield_mcp import server
from qfield_mcp.devices import (
    GROUPS_SUFFIX,
    OWNER_FILE,
    PREFIX,
    Devices,
    clean_orphans,
)

DEVICE = "mcp"
POINTS = "points"
PASSWORD = "not-a-secret"  # noqa: S105
NEW_POINT = (385000.0, 6672000.0)
# Shares the QField test project with pytest-qfield
DATA = Path(__file__).parents[2] / "pytest-qfield" / "test" / "data"


def call(tool: str, **arguments: Any) -> Any:  # noqa: ANN401
    result = asyncio.run(server.server.call_tool(tool, arguments))
    if isinstance(result, tuple):
        return result[1].get("result", result[1])
    if getattr(result, "structured_content", None) is not None:
        return result.structured_content.get("result", result.structured_content)
    if result.content and result.content[0].type == "text":
        return json.loads(result.content[0].text)
    return result


@pytest.fixture(scope="module")
def device() -> Iterator[str]:
    call("start_device", name=DEVICE)
    yield DEVICE
    if DEVICE in server.devices.names():
        call("stop_device", name=DEVICE)


@pytest.fixture(scope="module")
def project_device(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Start a device with a copy of the QField test project open."""
    target = tmp_path_factory.mktemp("project")
    shutil.copytree(DATA / "qfield_project", target, dirs_exist_ok=True)
    call("start_device", name="forms")
    call(
        "open_project",
        device="forms",
        path=str(target / "pytest-qfield-project_qfield.qgs"),
    )
    yield "forms"
    call("stop_device", name="forms")


@pytest.fixture
def fake_device() -> Iterator[str]:
    """Register a device that is no QField, for tools whose actions are replaced."""
    lock = server.devices.reserve("fake")
    server.devices.add("fake", type("App", (), {"process_groups": {}})())
    lock.release()
    yield "fake"
    server.devices.forget("fake")


def texts(device: str, expression: str = "") -> list[str]:
    rows = call(
        "features",
        layer=POINTS,
        fields=["text_field"],
        expression=expression,
        device=device,
    )
    return [row["text_field"] for row in rows]


@pytest.mark.qfield_app
def test_items_can_be_found_and_tapped(device: str) -> None:
    assert "#mapCanvas" in call("item_tree", device=device)
    found = call("find_items", query="local projects", device=device)
    assert "Local projects" in found
    clickable = call("item_tree", device=device, clickable_only=True)
    assert "[clickable]" in clickable
    assert "#stateMachine" not in clickable

    assert "true after" in call("wait_for", device=device, text="Local projects")
    assert "true after" in call("wait_for", device=device, text="Nope", gone=True)
    assert "tapped" in call("tap", device=device, text="Local projects")


def test_eval_js_description_names_the_qml_api_differences() -> None:
    tools = asyncio.run(server.server.list_tools())
    description = next(
        tool.description or "" for tool in tools if tool.name == "eval_js"
    )

    assert "mapLayersByName" in description
    assert "fields.names" in description


@pytest.mark.qfield_app
def test_tap_and_wait_explain_misses(device: str) -> None:
    with pytest.raises(Exception, match="No visible item with text"):
        call("tap", device=device, text="Nothing like this")
    with pytest.raises(Exception, match="Still not true"):
        call("wait_for", device=device, js="return false", timeout=0.5)
    with pytest.raises(Exception, match="No device 'nope'"):
        call("eval_js", code="return 1", device="nope")


@pytest.mark.qfield_app
def test_screenshot_scales_and_refuses_cameras(device: str, tmp_path: Path) -> None:
    full = call("screenshot", device=device)
    half = call("screenshot", device=device, scale=0.5)
    assert len(half.content[0].data) < len(full.content[0].data)

    fake = tmp_path / "CameraFake.qml"
    fake.write_text("import QtQuick\nItem { width: 10; height: 10 }\n")
    call(
        "eval_js",
        device=device,
        code=f"state.camera = Qt.createComponent('file://{fake}')"
        ".createObject(iface.mainWindow().contentItem);",
    )
    try:
        with pytest.raises(Exception, match="camera view is open"):
            call("screenshot", device=device)
    finally:
        call("eval_js", device=device, code="state.camera.destroy();")


@pytest.mark.qfield_app
def test_parallel_calls_get_their_own_results(device: str) -> None:
    with ThreadPoolExecutor(8) as pool:
        results = list(
            pool.map(
                lambda value: call("eval_js", device=device, code=f"return {value}"),
                range(40),
            )
        )

    assert results == list(range(40))


@pytest.mark.qfield_app
def test_reload_plugin_picks_up_edits(tmp_path: Path) -> None:
    (tmp_path / "main.qml").write_text("import QtQuick\nItem { property int v: 1 }\n")
    call("start_device", name="plugin", plugin_dir=str(tmp_path))
    try:
        (tmp_path / "main.qml").write_text(
            "import QtQuick\nItem { property int v: 2 }\n"
        )
        call("reload_plugin", device="plugin")

        assert call("eval_js", device="plugin", code="return plugin.v") == 2
    finally:
        call("stop_device", name="plugin")


@pytest.mark.qfield_app
def test_device_restarts_under_the_same_name(device: str) -> None:
    call("stop_device", name=device)
    call("start_device", name=device)

    assert call("list_devices") == [device]


@pytest.mark.qfield_app
def test_set_field_and_save_form_use_the_form_of_an_existing_feature(
    project_device: str,
) -> None:
    call(
        "open_feature_form",
        layer=POINTS,
        expression="text_field = 'test'",
        device=project_device,
    )
    call("set_field", label="text_field", value="edited", device=project_device)
    call("save_form", device=project_device)

    assert texts(project_device, "text_field = 'edited'") == ["edited"]
    call("close_feature_form", device=project_device)


@pytest.mark.qfield_app
def test_set_field_and_save_form_use_the_form_of_a_new_feature(
    project_device: str,
) -> None:
    call("frame_map", x=NEW_POINT[0], y=NEW_POINT[1], device=project_device)
    call("set_active_layer", layer=POINTS, device=project_device)
    call(
        "eval_js",
        code="iface.mainWindow().changeMode('digitize');",
        device=project_device,
    )
    call("tap_map", x=NEW_POINT[0], y=NEW_POINT[1], device=project_device)
    call(
        "wait_for",
        js="return find('overlayFeatureFormDrawer').opened",
        device=project_device,
    )

    call("set_field", label="text_field", value="new one", device=project_device)
    call("save_form", device=project_device)

    assert texts(project_device, "text_field = 'new one'") == ["new one"]
    call(
        "eval_js",
        code="iface.mainWindow().changeMode('browse');",
        device=project_device,
    )


@pytest.mark.qfield_app
def test_features_are_added_changed_and_deleted(project_device: str) -> None:
    before = len(texts(project_device))
    call("frame_map", x=NEW_POINT[0], y=NEW_POINT[1], device=project_device)

    call(
        "digitize_point",
        layer=POINTS,
        x=NEW_POINT[0],
        y=NEW_POINT[1],
        label="text_field",
        value="tapped",
        device=project_device,
    )
    call(
        "add_feature",
        layer=POINTS,
        attributes={"text_field": "coded"},
        wkt="Point (385020 6672000)",
        device=project_device,
    )
    call(
        "change_geometry",
        layer=POINTS,
        expression="text_field = 'coded'",
        wkt="Point (385030 6672000)",
        device=project_device,
    )

    assert len(texts(project_device)) == before + 2
    geometries = call(
        "eval_js",
        device=project_device,
        code="""
      const layer = qgisProject.mapLayersByName('points')[0];
      const it = LayerUtils.createFeatureIteratorFromExpression(layer, "text_field = 'coded'");
      const wkt = String(it.next().geometry.asWkt(0)); it.close(); return {wkt};""",
    )
    assert geometries == {"wkt": "Point (385030 6672000)"}

    call(
        "delete_feature",
        layer=POINTS,
        expression="text_field = 'coded'",
        device=project_device,
    )
    call(
        "delete_feature",
        layer=POINTS,
        expression="text_field = 'tapped'",
        device=project_device,
    )

    assert len(texts(project_device)) == before


def test_cloud_download_passes_the_plugin_grant_on(
    monkeypatch: pytest.MonkeyPatch, fake_device: str
) -> None:
    opened: list[bool] = []
    monkeypatch.setattr(
        server.actions, "download_project", lambda _app, _id: Path("/p.qgs")
    )
    monkeypatch.setattr(
        server.actions,
        "open_project",
        lambda _app, _path, *, grant_plugin=False: opened.append(grant_plugin),
    )
    call(
        "cloud_download", project_id="x", device=fake_device, grant_project_plugin=True
    )

    assert opened == [True]


class FakeStack:
    url = "https://cloud.test"
    admin = ("admin", "secret")
    ca_certificate = Path("/ca.pem")

    def __init__(self) -> None:
        self.users: list[tuple[str, str, bool]] = []

    def ensure_user(
        self, username: str, password: str, *, superuser: bool = False
    ) -> None:
        self.users.append((username, password, superuser))


class FakeClient:
    """Records what the cloud tools ask of a logged in user."""

    calls: list[tuple[Any, ...]] = []  # noqa: RUF012 shared on purpose

    def __init__(self, url: str, username: str, password: str, *, verify: Path) -> None:
        self.login = (url, username, password, verify)

    def create_project(self, name: str) -> str:
        self.calls.append(("create", self.login[1], name))
        return "project-id"

    def add_collaborator(
        self, project_id: str, username: str, role: str = "editor"
    ) -> None:
        self.calls.append(("collaborator", project_id, username, role))

    def upload(self, project_id: str, directory: Path) -> int:
        self.calls.append(("upload", project_id, directory))
        return 3

    def package(self, project_id: str) -> None:
        self.calls.append(("package", project_id))

    def deltas(self, project_id: str) -> list[dict[str, Any]]:
        return [
            {
                "id": "d1",
                "status": "STATUS_APPLIED",
                "created_by": "surveyor",
                "created_at": "now",
                "content": {"big": "payload"},
                "last_feedback": {"msg": f"Applied on {project_id}"},
            }
        ]


@pytest.fixture
def fake_cloud(monkeypatch: pytest.MonkeyPatch) -> FakeStack:
    stack = FakeStack()
    FakeClient.calls = []
    monkeypatch.setattr(server, "_stack", stack)
    monkeypatch.setattr(server, "_clients", {})
    monkeypatch.setattr("qfield_driver.cloud.client.QFieldCloudClient", FakeClient)
    return stack


def test_cloud_tools_need_a_stack(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_stack", None)

    with pytest.raises(Exception, match="cloud_up"):
        call("cloud_deltas", project_id="x")
    with pytest.raises(Exception, match="cloud_up"):
        call("cloud_user", username="a", password=PASSWORD)


def test_cloud_user_is_created_on_the_stack(fake_cloud: FakeStack) -> None:
    call("cloud_user", username="surveyor", password=PASSWORD)

    assert fake_cloud.users == [("surveyor", PASSWORD, False)]


@pytest.mark.usefixtures("fake_cloud")
def test_cloud_project_is_created_filled_and_packaged(tmp_path: Path) -> None:
    project_id = call(
        "cloud_create_project",
        name="demo",
        directory=str(tmp_path),
        collaborators=["surveyor"],
    )

    assert project_id == "project-id"
    assert FakeClient.calls == [
        ("create", "admin", "demo"),
        ("collaborator", "project-id", "surveyor", "editor"),
        ("upload", "project-id", tmp_path),
        ("package", "project-id"),
    ]


@pytest.mark.usefixtures("fake_cloud")
def test_cloud_tools_log_in_as_the_given_user_once() -> None:
    call("cloud_create_project", name="a", username="owner", password=PASSWORD)
    call(
        "cloud_add_collaborator",
        project_id="p",
        collaborator="c",
        role="reader",
        username="owner",
        password=PASSWORD,
    )

    assert FakeClient.calls == [
        ("create", "owner", "a"),
        ("collaborator", "p", "c", "reader"),
    ]
    assert len(server._clients) == 1
    with pytest.raises(Exception, match="together"):
        call("cloud_package", project_id="p", username="owner2")
    with pytest.raises(Exception, match="together"):
        call("cloud_package", project_id="p", password=PASSWORD)


@pytest.mark.usefixtures("fake_cloud")
def test_cloud_upload_refuses_a_missing_directory(tmp_path: Path) -> None:
    missing = tmp_path / "nope"

    with pytest.raises(Exception, match=f"Not a project directory: {missing}"):
        call("cloud_upload", project_id="p", directory=str(missing))
    with pytest.raises(Exception, match="Not a project directory"):
        call("cloud_create_project", name="x", directory=str(missing))

    assert FakeClient.calls == []


@pytest.mark.usefixtures("fake_cloud")
def test_cloud_upload_and_package_and_deltas(tmp_path: Path) -> None:
    assert (
        call("cloud_upload", project_id="p", directory=str(tmp_path))
        == "uploaded 3 files, packaged"
    )
    assert (
        call("cloud_upload", project_id="p", directory=str(tmp_path), package=False)
        == "uploaded 3 files"
    )
    call("cloud_package", project_id="p")

    assert call("cloud_deltas", project_id="p") == [
        {
            "id": "d1",
            "status": "STATUS_APPLIED",
            "created_by": "surveyor",
            "created_at": "now",
            "message": "Applied on p",
        }
    ]
    assert [c[0] for c in FakeClient.calls] == [
        "upload",
        "package",
        "upload",
        "package",
    ]


@pytest.mark.parametrize(
    ("pushed", "expected"),
    [
        ({"deltas": 2, "delta_status": "applied"}, "deltas pushed: 2, status applied"),
        ({"deltas": 0, "delta_status": None}, "no local changes to push"),
    ],
)
def test_cloud_synchronize_reports_deltas_and_status(
    monkeypatch: pytest.MonkeyPatch,
    fake_device: str,
    pushed: dict[str, Any],
    expected: str,
) -> None:
    monkeypatch.setattr(server.actions, "synchronize", lambda _app, _id: pushed)

    result = call("cloud_synchronize", project_id="x", device=fake_device)

    assert result == f"synchronized, {expected}"


def test_unusable_app_binary_is_named_in_the_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("QFIELD_APP_BINARY", str(tmp_path / "AppRun"))

    with pytest.raises(Exception, match=r"QFIELD_APP_BINARY.*`version`.*unset"):
        call("start_device", name="broken")

    assert "broken" not in server.devices.names()


def test_orphans_of_a_dead_server_are_stopped(tmp_path: Path) -> None:
    dead = subprocess.Popen(["true"])  # noqa: S607 coreutils from PATH
    dead.wait()
    orphan = subprocess.Popen(
        ["sleep", "60"],  # noqa: S607 coreutils from PATH
        start_new_session=True,
    )
    stranger = subprocess.Popen(
        ["sleep", "61"],  # noqa: S607 coreutils from PATH
        start_new_session=True,
    )
    work_dir = tmp_path / f"{PREFIX}old"
    work_dir.mkdir()
    (work_dir / OWNER_FILE).write_text(str(dead.pid))
    cmdline = Path(f"/proc/{orphan.pid}/cmdline").read_text()
    (work_dir / f"phone{GROUPS_SUFFIX}").write_text(
        json.dumps({str(orphan.pid): cmdline, str(stranger.pid): "something else"})
    )
    try:
        assert clean_orphans(tmp_path) == ["phone"]

        assert orphan.wait(5) != 0
        assert stranger.poll() is None
        assert not work_dir.exists()
    finally:
        orphan.kill()
        stranger.kill()


@pytest.mark.parametrize("name", ["", "../x", "/home/user", "a b"])
def test_device_names_must_be_plain(name: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must match"):
        Devices(tmp_path).reserve(name)
