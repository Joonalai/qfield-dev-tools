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

"""REST access to a QFieldCloud, the steps QField Sync and admins do by hand."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOGGER = logging.getLogger(__name__)

SKIPPED_SUFFIXES = (".gpkg-shm", ".gpkg-wal", "~")
DONE_JOB_STATES = frozenset({"finished", "failed", "stopped"})
PENDING_DELTA_STATES = frozenset({"STATUS_PENDING", "STATUS_BUSY"})
POLL_S = 3


class CloudError(RuntimeError):
    """QFieldCloud refused or failed a step."""


class QFieldCloudClient:
    """One logged in user.

    :param verify: Certificate authority of a local stack, see
        `QFieldCloudStack.ca_certificate`
    """

    def __init__(
        self,
        url: str,
        username: str,
        password: str,
        *,
        verify: Path | bool = True,
    ) -> None:
        self.url = url
        self.username = username
        self._api = f"{url}/api/v1"
        self._session = requests.Session()
        self._session.verify = str(verify) if isinstance(verify, Path) else verify
        # nginx drops idle keep-alive connections about as often as jobs are polled.
        self._session.mount("https://", HTTPAdapter(max_retries=Retry(total=3)))
        response = self._session.post(
            f"{self._api}/auth/login/",
            json={"username": username, "password": password},
            timeout=30,
        )
        response.raise_for_status()
        self.token = response.json()["token"]
        self._session.headers["Authorization"] = f"Token {self.token}"

    def get(self, path: str) -> Any:  # noqa: ANN401
        response = self._session.get(f"{self._api}{path}", timeout=60)
        response.raise_for_status()
        return response.json()

    def rows(self, path: str) -> list[dict[str, Any]]:
        body = self.get(path)
        return body["results"] if isinstance(body, dict) else body

    def create_project(self, name: str, *, owner: str | None = None) -> str:
        response = self._session.post(
            f"{self._api}/projects/",
            json={"name": name, "owner": owner or self.username},
            timeout=60,
        )
        if not response.ok:
            msg = f"Creating {name}: {response.text}"
            raise CloudError(msg)
        return response.json()["id"]

    def delete_project(self, project_id: str) -> None:
        self._session.delete(f"{self._api}/projects/{project_id}/", timeout=60)

    def add_collaborator(
        self, project_id: str, username: str, role: str = "editor"
    ) -> None:
        response = self._session.post(
            f"{self._api}/collaborators/{project_id}/",
            json={"collaborator": username, "role": role},
            timeout=60,
        )
        if not response.ok:
            msg = f"Adding {username}: {response.text}"
            raise CloudError(msg)

    def upload(self, project_id: str, directory: Path) -> int:
        """Upload a project directory, and return how many files went up."""
        files = [
            path
            for path in sorted(directory.rglob("*"))
            if path.is_file()
            and ".qfieldsync" not in path.parts
            and not path.name.endswith(SKIPPED_SUFFIXES)
        ]
        for path in files:
            name = quote(path.relative_to(directory).as_posix())
            with path.open("rb") as content:
                response = self._session.post(
                    f"{self._api}/files/{project_id}/{name}/",
                    files={"file": content},
                    timeout=300,
                )
            if not response.ok:
                msg = f"Uploading {name}: {response.text}"
                raise CloudError(msg)
        LOGGER.info("Uploaded %d files", len(files))
        return len(files)

    def files(self, project_id: str) -> list[dict[str, Any]]:
        return self.rows(f"/files/{project_id}/")

    def download(self, project_id: str, name: str, target: Path) -> Path:
        response = self._session.get(
            f"{self._api}/files/{project_id}/{quote(name)}/", timeout=300
        )
        response.raise_for_status()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.content)
        return target

    def jobs(self, project_id: str) -> list[dict[str, Any]]:
        return self.rows(f"/jobs/?project_id={project_id}")

    def package(self, project_id: str, timeout: float = 600) -> None:
        """Run a package job and every job already queued to the end."""
        response = self._session.post(
            f"{self._api}/jobs/",
            json={"project_id": project_id, "type": "package"},
            timeout=60,
        )
        if not response.ok:
            msg = f"Packaging {project_id}: {response.text}"
            raise CloudError(msg)
        self.wait_for_jobs(project_id, timeout)

    def wait_for_jobs(self, project_id: str, timeout: float = 600) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            jobs = self.jobs(project_id)
            if jobs and all(job["status"] in DONE_JOB_STATES for job in jobs):
                failed = [job for job in jobs if job["status"] != "finished"]
                if failed:
                    msg = f"Jobs failed: {failed}"
                    raise CloudError(msg)
                return
            time.sleep(POLL_S)
        msg = f"Jobs of {project_id} took over {timeout} s"
        raise TimeoutError(msg)

    def deltas(self, project_id: str) -> list[dict[str, Any]]:
        return self.rows(f"/deltas/{project_id}/")

    def wait_for_deltas(
        self, project_id: str, expected: int, timeout: float = 180
    ) -> list[dict[str, Any]]:
        """Wait until `expected` deltas are through, and return them all."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            deltas = self.deltas(project_id)
            done = [
                delta for delta in deltas if delta["status"] not in PENDING_DELTA_STATES
            ]
            if len(done) >= expected:
                return deltas
            time.sleep(POLL_S)
        msg = f"Fewer than {expected} deltas through on {project_id}"
        raise TimeoutError(msg)
