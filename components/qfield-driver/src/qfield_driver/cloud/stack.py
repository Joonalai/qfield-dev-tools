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

import fcntl
import hashlib
import json
import logging
import os
import re
import shutil
import socket
import ssl
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.request import Request, urlopen

from qfield_fetch import (
    LATEST,
    QFIELDCLOUD,
    Kind,
    entries,
    entry_path,
    latest_release,
    qfieldcloud_source,
    remove,
)

if TYPE_CHECKING:
    from collections.abc import Callable

LOGGER = logging.getLogger(__name__)

HERE = Path(__file__).parent
HOSTED_STATUS = "https://app.qfield.cloud/api/v1/status/"
HOSTED = "hosted"
SOURCE_ENV = "QFIELDCLOUD_SOURCE_DIR"
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


def resolve_ref(ref: str) -> str:
    """Resolve a tag or branch from `hosted`, `latest` or an explicit ref."""
    if ref == HOSTED:
        return hosted_ref()
    if ref == LATEST:
        return latest_release(QFIELDCLOUD)
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


def local_ref(source: Path) -> str:
    """Name a checkout of your own as a ref, `local-QFieldCloud` for example."""
    return f"local-{source.name}"


def compose_project_name(ref: str) -> str:
    return PROJECT_PREFIX + re.sub(r"[^a-z0-9]+", "_", ref.lower()).strip("_")


def _docker_tag(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", text).lstrip(".-")[:128] or "unknown"


def _git(source: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(source), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def source_version(source: Path, fallback: str) -> str:
    """Image tag naming the state of a checkout.

    `v26.30` for a release, `v26.30-3-gebfdcab` for commits after it. Edits that
    are not committed add a hash of the diff, so each edit builds anew.
    """
    if not (source / ".git").exists():
        return _docker_tag(fallback)
    try:
        version = _git(source, "describe", "--tags", "--always", "--dirty")
        if version.endswith("-dirty"):
            diff = _git(source, "diff", "HEAD")
            version += "-" + hashlib.sha256(diff.encode()).hexdigest()[:8]
    except (OSError, subprocess.CalledProcessError):
        return _docker_tag(fallback)
    return _docker_tag(version)


@dataclass
class QFieldCloudStack:
    """One local QFieldCloud.

    Ports are host ports bound to localhost. Only the object storage API also
    listens on `storage_host`, where the containers reach it.
    """

    ref: str
    # The qfield-fetch cache, which holds the checkout.
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
    # A QFieldCloud checkout of your own, used instead of a fetched one.
    source: Path | None = None
    # Set by `prepare_source`, a running stack then restarts what changed.
    reconfigured: bool = field(default=False, init=False)

    @classmethod
    def local(cls, source: Path, cache_dir: Path) -> QFieldCloudStack:
        """Return a stack running from a QFieldCloud checkout of your own.

        The stack writes its `.env` and compose overrides into the checkout.
        """
        source = source.expanduser().resolve()
        if not (source / ".env.example").is_file():
            msg = f"Not a QFieldCloud checkout: {source}"
            raise FileNotFoundError(msg)
        return cls(local_ref(source), cache_dir, source=source)

    @property
    def url(self) -> str:
        return f"https://localhost:{self.https_port}"

    @property
    def project_name(self) -> str:
        return self.name or compose_project_name(self.ref)

    @property
    def source_dir(self) -> Path:
        """The checkout the stack runs from."""
        return self.source or entry_path(Kind.QFIELDCLOUD, self.ref, self.cache_dir)

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
        """Fetch the release and write its configuration.

        Sets `reconfigured` when the configuration changed, the storage host
        follows the network for example.
        """
        source = self.source or qfieldcloud_source(self.ref, self.cache_dir)
        before = self._configuration(source)
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
        self.reconfigured = self._configuration(source) != before
        return source

    @staticmethod
    def _configuration(source: Path) -> list[str | None]:
        return [
            path.read_text() if path.exists() else None
            for path in (source / ".env", source / SERVICES_OVERRIDE)
        ]

    def _bind(self, port: dict[str, Any]) -> str:
        host = (
            self.storage_host
            if str(port["published"]) == str(self.storage_api_port)
            else "127.0.0.1"
        )
        protocol = port.get("protocol", "tcp")
        return f'"{host}:{port["published"]}:{port["target"]}/{protocol}"'

    def _services_override(self) -> str:
        """Override the upstream compose services for the tests.

        Drops log options podman rejects, disables unneeded services and binds
        the ports to localhost, upstream publishes them on all interfaces.
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
            ports = [port for port in spec.get("ports", []) if port.get("published")]
            if ports:
                lines.append("    ports: !override")
                lines += [f"      - {self._bind(port)}" for port in ports]
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
        # Without its own certificate authority, nothing of this stack answers.
        if not self.ca_certificate.exists():
            return False
        context = ssl.create_default_context(cafile=self.ca_certificate)
        url = f"{self.url}/api/v1/status/"
        try:
            with urlopen(url, timeout=5, context=context) as response:  # noqa: S310 the stack's https URL
                return json.load(response).get("database") == "ok"
        except (OSError, ValueError):
            return False

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

    @staticmethod
    def _docker(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["docker", *args], check=False, capture_output=True, text=True
        )

    def _images_missing(self, services: list[str], version: str) -> list[str]:
        """Services without an image of this version.

        Compose builds `<project>-<service>:latest`, the name the worker starts
        siblings from, so both tags must exist.
        """
        return [
            service
            for service in services
            if any(
                self._docker("image", "inspect", image).returncode
                for image in (
                    f"{self.project_name}-{service}",
                    f"{self.project_name}-{service}:{version}",
                )
            )
        ]

    def _tag_images(self, services: list[str], version: str) -> None:
        """Tag the built images with the version and drop older versions."""
        for service in services:
            repository = f"{self.project_name}-{service}"
            self._docker("image", "tag", repository, f"{repository}:{version}")
            tags = self._docker(
                "image", "ls", "--format", "{{.Tag}}", repository
            ).stdout.split()
            for tag in set(tags) - {"latest", version}:
                self._docker("image", "rm", f"{repository}:{tag}")

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
        """Build and start the stack unless it already answers.

        Idempotent, and safe from parallel processes such as pytest-xdist workers.
        """
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with (self.cache_dir / f".{self.project_name}.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self._up()

    def _up(self) -> None:
        source = self.prepare_source()
        version = source_version(source, self.ref)
        built = self.built_services()
        # Worker images run as siblings, a stack can answer while one is missing.
        missing = self._images_missing(built, version)
        if missing:
            LOGGER.info(
                "Building QFieldCloud %s %s, this takes a while", version, missing
            )
            self.compose("--profile", "*", "build", *missing)
            self._tag_images(built, version)
        elif self.is_up() and not self.reconfigured:
            if not self._runs_here():
                msg = (
                    f"Another QFieldCloud answers on port {self.https_port}, stop it"
                    " with `qfield-driver-cloud prune` or pick other"
                    " ports"
                )
                raise StackError(msg)
            LOGGER.info("QFieldCloud %s already running", version)
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
    for entry in entries(cache_dir):
        if entry.kind != Kind.QFIELDCLOUD or entry.name == keep:
            continue
        QFieldCloudStack(entry.name, cache_dir).down()
        remove(Kind.QFIELDCLOUD, entry.name, cache_dir)
        removed.append(entry.name)
    return removed
