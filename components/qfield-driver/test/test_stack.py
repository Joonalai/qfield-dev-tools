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
