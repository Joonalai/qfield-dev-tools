# Running QFieldCloud tests in a container

Files for running the QFieldCloud tests in a container, on a `qgis/qgis` base image.
They mount the engine socket, the repository and the qfield-fetch cache at their host
paths and set `DOCKER_HOST`, for the reasons in
[In a container](https://github.com/Joonalai/qfield-dev-tools/tree/main/components/qfield-driver#in-a-container).
They are adapted from a working setup, but not tested as they stand here, so treat
them as a starting point.

## Containerfile

```dockerfile
FROM qgis/qgis:3.44.8-noble
# What the QField AppImage does not bundle, plus a display.
RUN apt-get update && apt-get install -y --no-install-recommends \
        xvfb libegl1 libopengl0 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 \
        libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-xinerama0 \
        libxcb-xkb1 libdbus-1-3 libfontconfig1 git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
# Static docker CLI with the compose plugin.
RUN curl -fsSL https://download.docker.com/linux/static/stable/x86_64/docker-27.5.1.tgz \
        | tar -xz --strip-components=1 -C /usr/local/bin docker/docker \
    && mkdir -p /usr/local/lib/docker/cli-plugins \
    && curl -fsSL -o /usr/local/lib/docker/cli-plugins/docker-compose \
        https://github.com/docker/compose/releases/download/v2.36.0/docker-compose-linux-x86_64 \
    && chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
# Keep the venv out of the mounted repo, it would replace the host's `.venv`. It sees
# the QGIS bindings of the base image.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
RUN uv venv --system-site-packages --python /usr/bin/python3 /opt/venv
# Checkouts in the cache belong to the host user.
RUN git config --system --add safe.directory '*'
COPY entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
```

## entrypoint.sh

Syncs the venv against the mounted repository, runs the tests and hands the files it
created back to the host user.

```sh
#!/bin/sh
uv sync --all-groups
status=0
xvfb-run -a uv run pytest "$@" || status=$?
# Only set under rootful docker, rootless maps root to the host user anyway.
if [ -n "$HOST_UID" ]; then
    chown -R "$HOST_UID:${HOST_GID:-$HOST_UID}" "$QFIELD_FETCH_CACHE_DIR" "$PWD"
fi
exit $status
```

## compose.yml

The same paths on both sides. `CONTAINER_ENGINE_SOCKET` and `PWD` must be exported,
the Makefile target below does it.

```yaml
services:
  e2e:
    build: .
    working_dir: ${PWD}
    environment:
      DOCKER_HOST: unix://${CONTAINER_ENGINE_SOCKET}
      QFIELD_FETCH_CACHE_DIR: ${QFIELD_FETCH_CACHE_DIR:-$HOME/.cache/qfield-fetch}
      HOST_UID: ${HOST_UID:-}
      HOST_GID: ${HOST_GID:-}
    volumes:
      - ${CONTAINER_ENGINE_SOCKET}:${CONTAINER_ENGINE_SOCKET}
      - ${PWD}:${PWD}
      - ${QFIELD_FETCH_CACHE_DIR:-$HOME/.cache/qfield-fetch}:${QFIELD_FETCH_CACHE_DIR:-$HOME/.cache/qfield-fetch}
```

## Makefile

Finds the host socket in the same order as `container_socket()`.

```make
CONTAINER_ENGINE_SOCKET ?= $(or $(patsubst unix://%,%,$(filter unix://%,$(DOCKER_HOST))),$(wildcard $(XDG_RUNTIME_DIR)/podman/podman.sock),/var/run/docker.sock)

test-e2e-in-container:
	CONTAINER_ENGINE_SOCKET=$(CONTAINER_ENGINE_SOCKET) PWD=$(CURDIR) \
	HOST_UID=$(shell id -u) HOST_GID=$(shell id -g) \
	docker compose run --rm e2e
```
