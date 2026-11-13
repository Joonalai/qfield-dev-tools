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


import json
import re
import subprocess
from pathlib import Path

import pytest

from qfield_driver.cloud import stack as stack_module
from qfield_driver.cloud.stack import QFieldCloudStack

SERVICES = {
    "services": {
        "app": {},
        "nginx": {"ports": [{"target": 443, "published": "8543", "protocol": "tcp"}]},
        "rustfs": {
            "ports": [
                {"target": 9000, "published": "8109", "protocol": "tcp"},
                {"target": 9001, "published": "8113", "protocol": "tcp"},
            ]
        },
    }
}


@pytest.fixture
def stack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> QFieldCloudStack:
    """Return a stack whose checkout and compose are stand-ins."""
    source = tmp_path / "source"
    source.mkdir()
    (source / ".env.example").write_text(
        'STORAGES=\'{"default": {"endpoint_url": "http://172.17.0.1:8009"}}\'\n'
    )
    monkeypatch.setattr(stack_module, "qfieldcloud_source", lambda *_args: source)
    stack = QFieldCloudStack("v1", tmp_path, storage_host="192.0.2.5")
    monkeypatch.setattr(
        stack,
        "compose",
        lambda *args, **_kwargs: subprocess.CompletedProcess(
            args, 0, json.dumps(SERVICES), ""
        ),
    )
    return stack


def test_ports_bind_to_localhost_but_storage_api_to_the_storage_host(
    stack: QFieldCloudStack,
) -> None:
    assert stack._services_override() == (
        "services:\n"
        "  nginx:\n"
        "    ports: !override\n"
        '      - "127.0.0.1:8543:443/tcp"\n'
        "  rustfs:\n"
        "    ports: !override\n"
        '      - "192.0.2.5:8109:9000/tcp"\n'
        '      - "127.0.0.1:8113:9001/tcp"\n'
    )


def test_changed_configuration_is_noticed(stack: QFieldCloudStack) -> None:
    source = stack.prepare_source()
    first = stack.reconfigured
    stack.prepare_source()
    unchanged = stack.reconfigured
    stack.storage_host = "192.0.2.6"
    stack.prepare_source()

    assert (first, unchanged, stack.reconfigured) == (True, False, True)
    assert "http://192.0.2.6:8109" in (source / ".env").read_text()


def test_own_checkout_runs_without_fetching(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "QFieldCloud"
    checkout.mkdir()
    (checkout / ".env.example").write_text("WEB_HTTP_PORT=80\n")
    monkeypatch.setattr(stack_module, "qfieldcloud_source", pytest.fail)
    stack = QFieldCloudStack.local(checkout, tmp_path / "cache")
    monkeypatch.setattr(
        stack,
        "compose",
        lambda *args, **_kwargs: subprocess.CompletedProcess(
            args, 0, json.dumps(SERVICES), ""
        ),
    )

    assert stack.prepare_source() == checkout == stack.source_dir
    assert (stack.ref, stack.project_name) == (
        "local-QFieldCloud",
        "pytest_qfieldcloud_local_qfieldcloud",
    )
    assert "WEB_HTTP_PORT=8180" in (checkout / ".env").read_text()


def test_own_checkout_must_be_qfieldcloud(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Not a QFieldCloud checkout"):
        QFieldCloudStack.local(tmp_path, tmp_path / "cache")


def _git(repo: Path, *args: str) -> None:
    identity = ("-c", "user.name=test", "-c", "user.email=test@localhost")
    subprocess.run(  # noqa: S603 fixed git arguments
        ["git", "-C", str(repo), *identity, *args],  # noqa: S607 git from PATH
        check=True,
        capture_output=True,
    )


def test_source_version_follows_commits_and_edits(tmp_path: Path) -> None:
    """Every commit and every uncommitted edit names a new version."""
    (tmp_path / "app.py").write_text("one\n")
    _git(tmp_path, "init")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "one")
    _git(tmp_path, "tag", "v1.0")
    release = stack_module.source_version(tmp_path, "v1.0")
    (tmp_path / "app.py").write_text("two\n")
    edited = stack_module.source_version(tmp_path, "v1.0")
    (tmp_path / "app.py").write_text("three\n")
    edited_again = stack_module.source_version(tmp_path, "v1.0")
    _git(tmp_path, "commit", "-am", "three")
    committed = stack_module.source_version(tmp_path, "v1.0")

    assert release == "v1.0"
    assert edited.startswith("v1.0-dirty-")
    assert edited_again.startswith("v1.0-dirty-")
    assert edited != edited_again
    assert re.fullmatch(r"v1\.0-1-g[0-9a-f]+", committed)


def test_source_version_without_git_is_the_ref(tmp_path: Path) -> None:
    assert stack_module.source_version(tmp_path, "local-My Cloud") == "local-My_Cloud"


def test_images_are_tagged_with_the_version(
    stack: QFieldCloudStack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A new version builds again, and older version tags are dropped."""
    images = {"pytest_qfieldcloud_v1-app": {"latest", "old"}}

    def docker(*args: str) -> subprocess.CompletedProcess[str]:
        # The image named last is the one acted on, the target of `tag`.
        command, image = args[1], args[-1]
        repository, _, tag = image.partition(":")
        tags = images.setdefault(repository, set())
        stdout, returncode = "", 0
        if command == "inspect":
            returncode = int((tag or "latest") not in tags)
        elif command == "tag":
            tags.add(tag)
        elif command == "ls":
            stdout = "\n".join(tags)
        elif command == "rm":
            tags.discard(tag)
        return subprocess.CompletedProcess(args, returncode, stdout, "")

    monkeypatch.setattr(stack, "_docker", docker)

    missing = stack._images_missing(["app"], "new")
    stack._tag_images(["app"], "new")

    assert missing == ["app"]
    assert stack._images_missing(["app"], "new") == []
    assert images["pytest_qfieldcloud_v1-app"] == {"latest", "new"}
