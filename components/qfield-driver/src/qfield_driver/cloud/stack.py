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

"""The official QFieldCloud docker compose stack, at a chosen release.

QFieldCloud ships often and only the newest release is maintained, so the ref
defaults to whatever app.qfield.cloud runs. Each ref gets its own compose
project, images and volumes, and `down_stale` removes the older ones.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from collections.abc import Callable

LOGGER = logging.getLogger(__name__)

HERE = Path(__file__).parent
REPOSITORY = "https://github.com/opengisch/QFieldCloud.git"
HOSTED_STATUS = "https://app.qfield.cloud/api/v1/status/"
LATEST_API = "https://api.github.com/repos/opengisch/QFieldCloud/releases/latest"
HOSTED = "hosted"
LATEST = "latest"
OVERRIDE = "docker-compose.override.pytest.yml"
# Generated per release, services differ between releases.
SERVICES_OVERRIDE = "docker-compose.override.pytest-services.yml"
UPSTREAM_FILES = ("docker-compose.yml", "docker-compose.override.standalone.yml")
# Started by hand to avoid its scheduled jobs.
DISABLED_SERVICES = ("ofelia",)
RESOLVER_SCRIPT = "nginx-fix-resolver.sh"
PROJECT_PREFIX = "pytest_qfieldcloud_"
READY_TIMEOUT_S = 300
ADMIN = ("admin", "admin123")


class StackError(RuntimeError):
    """The QFieldCloud stack failed to build or start."""


def _get_json(url: str) -> dict[str, object]:
    request = Request(url, headers={"Accept": "application/json"})  # noqa: S310 fixed https URLs
    with urlopen(request, timeout=30) as response:  # noqa: S310 fixed https URLs
        return json.load(response)


def hosted_ref() -> str:
    """Release app.qfield.cloud runs, `v26.30` for its `v26.30-1`."""
    version = str(_get_json(HOSTED_STATUS)["version"])
    return version.split("-", maxsplit=1)[0]


def latest_ref() -> str:
    return str(_get_json(LATEST_API)["tag_name"])


def resolve_ref(ref: str) -> str:
    """Resolve a tag or branch from `hosted`, `latest` or an explicit ref."""
    if ref == HOSTED:
        return hosted_ref()
    if ref == LATEST:
        return latest_ref()
    return ref


def container_socket() -> str:
    """Host path of the socket the worker uses for sibling containers."""
    host = os.environ.get("DOCKER_HOST", "")
    if host.startswith("unix://"):
        return host.removeprefix("unix://")
    podman = Path(os.environ.get("XDG_RUNTIME_DIR", "/nonexistent"))
    podman /= "podman/podman.sock"
    return str(podman) if podman.exists() else "/var/run/docker.sock"


def host_address() -> str:
    """Return an address of this machine both containers and the host reach.

    The upstream default, docker's bridge 172.17.0.1, does not exist under podman.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            # Connecting a UDP socket sends nothing, it only picks a route.
            probe.connect(("192.0.2.1", 9))
            return str(probe.getsockname()[0])
        except OSError:
            return "172.17.0.1"


def render_env(example: str, overrides: dict[str, str]) -> str:
    """Return the upstream `.env.example` with the given keys replaced or appended."""
    missing = dict(overrides)
    lines = []
    for line in example.splitlines():
        match = re.match(r"^([A-Z0-9_]+)=", line)
        if match and match[1] in missing:
            key = match[1]
            lines.append(f"{key}={missing.pop(key)}")
        else:
            lines.append(line)
    lines.extend(f"{key}={value}" for key, value in missing.items())
    return "\n".join(lines) + "\n"


def compose_project_name(ref: str) -> str:
    return PROJECT_PREFIX + re.sub(r"[^a-z0-9]+", "_", ref.lower()).strip("_")


@dataclass
class QFieldCloudStack:
    """One local QFieldCloud.

    Ports are host ports, published on all interfaces like upstream does.
    """

    ref: str
    cache_dir: Path
    https_port: int = 8543
    http_port: int = 8180
    postgres_port: int = 8432
    storage_port: int = 8113
    storage_api_port: int = 8109
    # Host in storage endpoint URLs, see `host_address`.
    storage_host: str = field(default_factory=host_address)
    admin: tuple[str, str] = ADMIN
    extra_env: dict[str, str] = field(default_factory=dict)
    # Compose project, derived from the ref unless given.
    name: str | None = None

    @property
    def url(self) -> str:
        return f"https://localhost:{self.https_port}"

    @property
    def project_name(self) -> str:
        return self.name or compose_project_name(self.ref)

    @property
    def source_dir(self) -> Path:
        return self.cache_dir / f"QFieldCloud-{self.ref}"

    @property
    def ca_certificate(self) -> Path:
        """CA of the stack's self-signed certificate, written by mkcert."""
        return self.source_dir / "conf/nginx/certs/rootCA.pem"

    def env_overrides(self) -> dict[str, str]:
        return {
            "COMPOSE_PROJECT_NAME": self.project_name,
            "COMPOSE_FILE": ":".join((*UPSTREAM_FILES, OVERRIDE, SERVICES_OVERRIDE)),
            "WEB_HTTP_PORT": str(self.http_port),
            "WEB_HTTPS_PORT": str(self.https_port),
            "OBJECT_STORAGE_BROWSER_PORT": str(self.storage_port),
            "OBJECT_STORAGE_API_PORT": str(self.storage_api_port),
            "HOST_POSTGRES_PORT": str(self.postgres_port),
            "SMTP4DEV_SMTP_PORT": str(self.http_port + 2),
            "SMTP4DEV_IMAP_PORT": str(self.http_port + 3),
            "SMTP4DEV_WEB_PORT": str(self.http_port + 4),
            "DEBUG_APP_DEBUGPY_PORT": '""',
            "DEBUG_WORKER_WRAPPER_DEBUGPY_PORT": '""',
            # wrapper.py hands its own /tmp path to the sibling, so it must match.
            "TMP_DIRECTORY": "/tmp",  # noqa: S108 path inside the container
            "PYTEST_QFIELDCLOUD_SOCKET": container_socket(),
            **self.extra_env,
        }

    def prepare_source(self) -> Path:
        source = self.source_dir
        if not source.exists():
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    *("git", "clone", "--quiet", "--depth=1"),
                    f"--branch={self.ref}",
                    REPOSITORY,
                    str(source),
                ],
                check=True,
            )
        shutil.copy(HERE / OVERRIDE, source / OVERRIDE)
        shutil.copy(HERE / RESOLVER_SCRIPT, source / RESOLVER_SCRIPT)
        env = render_env((source / ".env.example").read_text(), self.env_overrides())
        # Storage endpoints must reach the published API port from containers
        # and from the host alike.
        env = re.sub(
            r'("endpoint_url":\s*"http://)[^:"]+:\d+',
            rf"\g<1>{self.storage_host}:{self.storage_api_port}",
            env,
        )
        (source / ".env").write_text(env)
        (source / SERVICES_OVERRIDE).write_text(self._services_override())
        return source

    def _services_override(self) -> str:
        """Override the upstream compose services for the tests.

        Drops log options podman rejects, and disables unneeded services.
        """
        upstream = [f"--file={name}" for name in UPSTREAM_FILES]
        completed = self.compose(
            *upstream, "--profile", "*", "config", "--format", "json"
        )
        lines = ["services:"]
        for name, spec in json.loads(completed.stdout)["services"].items():
            lines.append(f"  {name}:")
            if name in DISABLED_SERVICES:
                lines.append("    profiles: [disabled]")
            if "logging" in spec:
                lines += ["    logging: !override", "      driver: json-file"]
            if lines[-1] == f"  {name}:":
                lines.pop()
        return "\n".join(lines) + "\n"

    def compose(
        self, *args: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        # The upstream compose file resolves a volume through $PWD.
        completed = subprocess.run(
            ["docker", "compose", *args],
            cwd=self.source_dir,
            env={**os.environ, "PWD": str(self.source_dir)},
            check=False,
            text=True,
            capture_output=True,
        )
        if check and completed.returncode:
            msg = f"compose {args} failed:\n{completed.stderr[-3000:]}"
            raise StackError(msg)
        return completed

    def manage(self, *args: str, check: bool = True) -> str:
        """Run a Django management command in the app container."""
        return self.compose(
            *("exec", "-T", "app", "python", "manage.py"), *args, check=check
        ).stdout

    def is_up(self) -> bool:
        # The cloud extra provides these, the fixtures load without it.
        import requests  # noqa: PLC0415
        import urllib3  # noqa: PLC0415

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        try:
            response = requests.get(
                f"{self.url}/api/v1/status/",
                verify=False,  # noqa: S501 the local stack has a self-signed certificate
                timeout=5,
            )
        except requests.RequestException:
            return False
        return response.ok and response.json().get("database") == "ok"

    def _runs_here(self) -> bool:
        """Whether this ref's own app container is running."""
        return bool(self.compose("ps", "--quiet", "app", check=False).stdout.strip())

    def built_services(self) -> list[str]:
        """Services the release builds itself, profiles included.

        Read from the compose files, releases add some, `qgis4` in v26.30.
        """
        completed = self.compose(
            "--profile", "*", "config", "--format", "json", check=True
        )
        services = json.loads(completed.stdout)["services"]
        return sorted(name for name, spec in services.items() if "build" in spec)

    def _images_missing(self, services: list[str]) -> list[str]:
        return [
            service
            for service in services
            if subprocess.run(
                ["docker", "image", "inspect", f"{self.project_name}-{service}"],
                check=False,
                capture_output=True,
            ).returncode
        ]

    def _wait(
        self, what: str, ready: Callable[[], bool], timeout: float = READY_TIMEOUT_S
    ) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if ready():
                return
            time.sleep(2)
        msg = f"{what} not ready after {timeout} s"
        raise StackError(msg)

    def up(self) -> None:
        """Build and start the stack unless it already answers. Idempotent."""
        self.prepare_source()
        # Worker images run as siblings, a stack can answer while one is missing.
        missing = self._images_missing(self.built_services())
        if missing:
            LOGGER.info(
                "Building QFieldCloud %s %s, this takes a while", self.ref, missing
            )
            self.compose("--profile", "*", "build", *missing)
        elif self.is_up():
            if not self._runs_here():
                msg = (
                    f"Another QFieldCloud answers on port {self.https_port}, stop it"
                    " with `python -m qfield_driver.cloud prune` or pick other"
                    " ports"
                )
                raise StackError(msg)
            LOGGER.info("QFieldCloud %s already running", self.ref)
            return
        self.compose("up", "-d", "--no-build", "db", "memcached", "mkcert")
        self._wait(
            "QFieldCloud database",
            lambda: (
                self.compose(
                    "exec", "-T", "db", "pg_isready", "-q", check=False
                ).returncode
                == 0
            ),
        )
        # Object storage changed from minio to rustfs over releases, start
        # whatever this release has.
        services = self.compose("config", "--services").stdout.split()
        storage = [service for service in ("minio", "rustfs") if service in services]
        self.compose("up", "-d", "--no-build", *storage, "app")
        self._wait(
            "QFieldCloud app",
            lambda: (
                self.compose("exec", "-T", "app", "true", check=False).returncode == 0
            ),
        )
        self.manage("migrate", "--no-input")
        self.manage("collectstatic", "--no-input")
        self.ensure_user(*self.admin, superuser=True)
        workers = [
            service
            for service in ("createbuckets", "nginx", "worker_wrapper")
            if service in services
        ]
        self.compose("up", "-d", "--no-build", *workers)
        self._wait("QFieldCloud", self.is_up)

    def ensure_user(
        self, username: str, password: str, *, superuser: bool = False
    ) -> None:
        """Create a user, or leave an existing one alone."""
        self.manage(
            "createuser",
            f"--username={username}",
            f"--email={username}@localhost.local",
            f"--password={password}",
            *(["--superuser"] if superuser else []),
            check=False,
        )

    def logs(self, *services: str, tail: int = 200) -> str:
        return self.compose("logs", f"--tail={tail}", *services, check=False).stdout

    def down(self) -> None:
        """Remove the stack and its data volumes, keep the images."""
        if self.source_dir.exists():
            self.compose("down", "-v", "--remove-orphans", check=False)


def down_stale(cache_dir: Path, keep: str) -> list[str]:
    """Remove stacks of other refs, and return the refs removed."""
    removed = []
    for source in sorted(cache_dir.glob("QFieldCloud-*")):
        ref = source.name.removeprefix("QFieldCloud-")
        if ref == keep:
            continue
        QFieldCloudStack(ref, cache_dir).down()
        shutil.rmtree(source, ignore_errors=True)
        removed.append(ref)
    return removed
