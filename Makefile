# Development shortcuts, see DEVELOPMENT.md. `make` lists the targets.

.DEFAULT_GOAL := help
# Every test target syncs its own component into the shared .venv
.NOTPARALLEL:

export QT_QPA_PLATFORM := offscreen

# The Python QGIS uses
SYSTEM_PYTHON ?= /usr/bin/python3
# Extra pytest arguments, e.g. make test-e2e ARGS="-k reuse -x"
ARGS ?=

APP_GROUPS := --all-extras --all-groups

.PHONY: help venv sync-pytest-qfield pyqt test test-fetch test-qfield test-driver \
    test-e2e test-mcp test-cloud cloud-up cloud-down lint hooks lock

help: ## Show the targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-z0-9%-]+:.*## / {sub("%", "<component>", $$1); printf "  %-22s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

venv: ## Create .venv on the system Python, so QGIS is visible
	uv venv --system-site-packages --python $(SYSTEM_PYTHON)

sync-%: ## Install one component and its groups into .venv
	uv sync --package $* $(APP_GROUPS)

sync-pytest-qfield:
	uv sync --package pytest-qfield --all-groups
	@$(MAKE) --no-print-directory pyqt

pyqt: ## Add the PyQt6 wheel matching the system Qt, uv sync removes it
	uv pip install "PyQt6==$$($(SYSTEM_PYTHON) -c "from PyQt6.QtCore import QT_VERSION_STR; print(QT_VERSION_STR.rsplit('.', 1)[0])").*"

test: test-fetch test-qfield test-driver test-e2e test-mcp ## Run every suite except the cloud tests

test-fetch: sync-qfield-fetch ## qfield-fetch tests
	uv run --no-sync pytest components/qfield-fetch $(ARGS)

test-qfield: sync-pytest-qfield ## pytest-qfield tests
	uv run --no-sync pytest --qgis_disable_gui components/pytest-qfield $(ARGS)

test-driver: sync-qfield-driver ## qfield-driver tests
	uv run --no-sync pytest components/qfield-driver/test $(ARGS)

test-e2e: sync-pytest-qfield-e2e ## pytest-qfield-e2e tests, without QFieldCloud
	uv run --no-sync pytest -m "not qfieldcloud" components/pytest-qfield-e2e/test $(ARGS)

test-mcp: sync-qfield-mcp ## qfield-mcp tests
	uv run --no-sync pytest components/qfield-mcp/test $(ARGS)

test-cloud: sync-pytest-qfield-e2e ## QFieldCloud tests, slow, removes the stack afterwards
	uv run --no-sync pytest -m qfieldcloud --qfieldcloud-down components/pytest-qfield-e2e/test $(ARGS)

cloud-up: sync-qfield-driver ## Build and start the local QFieldCloud of the hosted release
	uv run --no-sync qfdc up

cloud-down: sync-qfield-driver ## Remove the local QFieldCloud
	uv run --no-sync qfdc down

lint: ## Run all hooks on all files
	uv run prek run --all-files

hooks: ## Install the pre-commit and commit-msg hooks
	uv run prek install

lock: ## Update uv.lock
	uv lock
