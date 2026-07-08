path := .

# ── Paths & images ────────────────────────────────────────────────────────────
BIN                := ./bin
DIST_DIR           ?= dist
GHCR_REGISTRY      ?= ghcr.io
GHCR_OWNER         ?= exegia
CORPORA_IMAGE      ?= $(GHCR_REGISTRY)/$(GHCR_OWNER)/corpora-py
PYTHON_VERSION     ?= 3.13
DOCKER_PROJECT     := docker compose --project-directory .
DOCKER_COMPOSE_CORPORA := $(DOCKER_PROJECT) -f dockerfiles/docker-compose.yml

# Optional args forwarded to bin scripts (e.g. make publish PUBLISH_ARGS=minor)
PUBLISH_ARGS       ?=
BUILD_ARGS         ?=
EMBEDDED_ARGS      ?=
IMAGE_TAG          ?= latest

define Comment
	- Run `make help` to see all available targets.
	- Run `make setup` to install all dependencies.
	- Run `make clean` to remove caches, build artifacts, and venv.
	- Run `make build-wheel` to build workspace wheels into dist/.
	- Run `make docker-up-corpora` to start containers.
	- Run `make publish` to bump version, tag, and trigger PyPI publish via CI.
	- Run `make docker-publish` to build and push images to GHCR.
endef

# ── Setup & dependencies ──────────────────────────────────────────────────────

.PHONY: setup
setup: ## Install all dependencies (uv sync, dotenvx, example deps, embedded Python).
	@chmod +x $(BIN)/setup.sh $(BIN)/utils.sh
	@$(BIN)/setup.sh

.PHONY: clean
clean: ## Remove caches, build artifacts, venv, and node_modules.
	@chmod +x $(BIN)/clean.sh
	@$(BIN)/clean.sh

.PHONY: dep-lock
dep-lock: ## Lock dependencies in uv.lock.
	@uv lock

.PHONY: dep-sync
dep-sync: ## Sync venv installation with uv.lock.
	@uv sync

.PHONY: dep-update
dep-update: ## Update all dependencies (regenerate lock + venv).
	@chmod +x $(BIN)/update_deps.sh
	@$(BIN)/update_deps.sh

# ── Build ─────────────────────────────────────────────────────────────────────

.PHONY: build-wheel
build-wheel: ## Build all workspace wheels into dist/.
	@chmod +x $(BIN)/build/wheel.sh $(BIN)/build/common.sh
	@$(BIN)/build/wheel.sh build $(DIST_DIR)

.PHONY: build-bundle
build-bundle: ## Build sidecar / Tauri resource bundle (wheels + standalone Python).
	@chmod +x $(BIN)/build/*.sh
	@$(BIN)/build/build.sh $(BUILD_ARGS)

.PHONY: generate-dockerfiles
generate-dockerfiles: ## Regenerate versioned Python Dockerfiles from template.
	@chmod +x $(BIN)/generate_dockerfile.sh
	@$(BIN)/generate_dockerfile.sh

# ── Lint & test ───────────────────────────────────────────────────────────────

.PHONY: lint
lint: ruff mypy ## Apply all linters.

.PHONY: lint-check
lint-check: ## Check whether the codebase satisfies linter rules.
	@echo
	@echo "Checking linter rules..."
	@echo "========================"
	@echo
	@uv run ruff check $(path)
	@uv run mypy $(path)

.PHONY: ruff
ruff: ## Apply ruff (check --fix + format).
	@echo "Applying ruff..."
	@echo "================"
	@echo
	@uv run ruff check --fix $(path)
	@uv run ruff format $(path)

.PHONY: mypy
mypy: ## Run mypy type checker.
	@echo
	@echo "Applying mypy..."
	@echo "================="
	@echo
	@uv run mypy $(path)

.PHONY: test
test: ## Run pytest.
	@uv run pytest -vv

# ── Docker — local containers ───────────────────────────────────────────────

.PHONY: docker-up-corpora
docker-up-corpora: ## Start corpora-py platform containers with AUTH_REQUIRED=false (local/example use).
	AUTH_REQUIRED=false PYTHON_VERSION=$(PYTHON_VERSION) $(DOCKER_COMPOSE_CORPORA) up --build -d

.PHONY: docker-down-corpora
docker-down-corpora: ## Stop corpora-py platform containers.
	$(DOCKER_COMPOSE_CORPORA) down

# ── Docker — build & publish to GHCR ─────────────────────────────────────────

.PHONY: docker-login-ghcr
docker-login-ghcr: ## Authenticate Docker with GHCR (uses GITHUB_TOKEN or gh CLI).
	@if [ -n "$$GITHUB_TOKEN" ]; then \
		token="$$GITHUB_TOKEN"; \
		user="$${GHCR_USER:-$(GHCR_OWNER)}"; \
	elif command -v gh >/dev/null 2>&1; then \
		token="$$(gh auth token)"; \
		user="$$(gh api user -q .login)"; \
	else \
		echo "error: set GITHUB_TOKEN or install the gh CLI" >&2; \
		exit 1; \
	fi; \
	echo "$$token" | docker login $(GHCR_REGISTRY) -u "$$user" --password-stdin

.PHONY: docker-build-corpora
docker-build-corpora: ## Build corpora-py Docker image locally.
	docker build -f dockerfiles/Dockerfile -t $(CORPORA_IMAGE):$(IMAGE_TAG) .

.PHONY: docker-publish-corpora
docker-publish-corpora: docker-login-ghcr docker-build-corpora ## Build and push corpora-py image to GHCR.
	docker push $(CORPORA_IMAGE):$(IMAGE_TAG)

.PHONY: docker-publish
docker-publish: docker-publish-corpora ## Build and push all images to GHCR.

# ── Publish (PyPI via GitHub Actions) ─────────────────────────────────────────

.PHONY: publish
publish: ## Bump version, commit, tag, and trigger PyPI publish (default: patch).
	@chmod +x $(BIN)/publish.sh
	@$(BIN)/publish.sh $(PUBLISH_ARGS)

.PHONY: publish-dispatch
publish-dispatch: ## Dispatch publish workflow without a version bump.
	@chmod +x $(BIN)/publish.sh
	@$(BIN)/publish.sh --dispatch $(PUBLISH_ARGS)

# ── Dev servers ───────────────────────────────────────────────────────────────

.PHONY: dev

# Run dev servers, but only after ensuring dist/ exists
dev: dist
	@bun --cwd=example concurrently -n vite,electron -c cyan,magenta -k "vite dev" "electrobun dev"

# Build dist/ only if it's missing (real target = file-existence check)
dist:
	@bun --cwd=example run vite:build

.PHONY: dev-web
dev-web: ## Start web-only (vite) server
	@bun --cwd=example vite dev

.PHONY: dev-stop
dev-stop: ## Stop dev processes.
	@chmod +x $(BIN)/stop.sh
	@$(BIN)/stop.sh

# ── Help ──────────────────────────────────────────────────────────────────────

.PHONY: help
help: ## Show this help message.
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-24s\033[0m %s\n", $$1, $$2}'

.PHONY: clean-all
clean-all: ## Delete all caches, generated files, build artifacts, venv, node_modules, and lock files.
	@echo "Cleaning all caches, generated files, and build artifacts..."
	@for path in \
		.venv \
		.cache \
		.pytest_cache \
		.mypy_cache \
		.ruff_cache \
		__pycache__ \
		$(DIST_DIR) \
		dist \
		build \
		*.egg-info \
		example/node_modules \
		example/.vite \
		example/.react-router \
		example/dist \
		example/build \
		node_modules \
		uv.lock \
		.dotenvx; do \
		for match in $$path; do \
			if [ -e "$$match" ]; then \
				echo "  removing $$match"; \
				rm -rf "$$match"; \
			fi; \
		done; \
	done
	@echo "Searching for nested cache directories and compiled Python files..."
	@find . -type d \( -name "__pycache__" -o -name ".pytest_cache" -o -name ".mypy_cache" -o -name ".ruff_cache" \) \
		-not -path "./.venv/*" -not -path "./node_modules/*" -not -path "./example/node_modules/*" \
		-print -exec rm -rf {} + 2>/dev/null || true
	@find . -type f \( -name "*.pyc" -o -name "*.pyo" \) \
		-not -path "./.venv/*" -not -path "./node_modules/*" -not -path "./example/node_modules/*" \
		-print -delete 2>/dev/null || true
	@echo "All caches and generated files have been removed."
