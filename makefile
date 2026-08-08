path := .

# ── Paths & images ────────────────────────────────────────────────────────────
BIN                := ./bin
DIST_DIR           ?= dist
GHCR_REGISTRY      ?= ghcr.io
GHCR_OWNER         ?= exegia
CORPORA_IMAGE      ?= $(GHCR_REGISTRY)/$(GHCR_OWNER)/corpora-py
GITHUB_TOKEN       ?= $GITHUB_ACCESS_TOKEN
# Vercel Container Registry (VCR). Image ref is registry/team-slug/project-slug/repository.
# Override VCR_TEAM/VCR_PROJECT/VCR_REPOSITORY to match your Vercel project.
VCR_REGISTRY       ?= vcr.vercel.com
VCR_TEAM           ?= exegia
VCR_PROJECT        ?= corpora-py
VCR_REPOSITORY     ?= corpora-py
VCR_IMAGE          ?= $(VCR_REGISTRY)/$(VCR_TEAM)/$(VCR_PROJECT)/$(VCR_REPOSITORY)
VCR_PLATFORMS      ?= linux/amd64,linux/arm64
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
	- Run `make docker-publish-vcr` to build and push the image to Vercel Container Registry.
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

.PHONY: supabase-pull-image
supabase-pull-image: docker-login-ghcr ## Authenticate Docker with GHCR (uses GITHUB_TOKEN or gh CLI).
	@docker pull $(GHCR_REGISTRY)/$(GHCR_OWNER)/corpora-supabase:latest

.PHONY: docker-build-corpora
docker-build-corpora: ## Build corpora-py Docker image locally.
	docker build -f dockerfiles/Dockerfile -t $(CORPORA_IMAGE):$(IMAGE_TAG) .

.PHONY: docker-publish-corpora
docker-publish-corpora: docker-login-ghcr docker-build-corpora ## Build and push corpora-py image to GHCR.
	docker push $(CORPORA_IMAGE):$(IMAGE_TAG)

.PHONY: docker-publish
docker-publish: docker-publish-corpora ## Build and push all images to GHCR.

# ── Docker — build & publish to Vercel Container Registry (VCR) ───────────────

.PHONY: vercel-env
vercel-env: ## Link the Vercel project and pull env vars into .env.local (provides VERCEL_OIDC_TOKEN).
	vercel link
	vercel env pull .env.local

.PHONY: docker-login-vcr
docker-login-vcr: ## Authenticate Docker with VCR (OIDC via VERCEL_OIDC_TOKEN, or token via VERCEL_TOKEN + VERCEL_TEAM_ID).
	@set -a; [ -f .env.local ] && . ./.env.local; set +a; \
	if [ -n "$$VERCEL_OIDC_TOKEN" ]; then \
		printf '%s' "$$VERCEL_OIDC_TOKEN" | docker login $(VCR_REGISTRY) --username oidc --password-stdin; \
	elif [ -n "$$VERCEL_TOKEN" ]; then \
		printf '%s' "$$VERCEL_TOKEN" | docker login $(VCR_REGISTRY) --username "$${VERCEL_TEAM_ID:?set VERCEL_TEAM_ID for token auth}" --password-stdin; \
	else \
		echo "error: set VERCEL_OIDC_TOKEN (run 'make vercel-env' then retry) or VERCEL_TOKEN" >&2; \
		exit 1; \
	fi

.PHONY: docker-publish-vcr
docker-publish-vcr: docker-login-vcr ## Build multi-arch image with zstd and push to VCR (requires docker buildx).
	docker buildx build \
		--platform $(VCR_PLATFORMS) \
		-f dockerfiles/Dockerfile \
		--output "type=image,name=$(VCR_IMAGE):$(IMAGE_TAG),push=true,oci-mediatypes=true,compression=zstd,compression-level=3,force-compression=true" \
		.

# ── Publish (PyPI via GitHub Actions) ─────────────────────────────────────────

.PHONY: publish
publish: ## Bump version, commit, tag, and trigger PyPI publish (default: patch).
	@chmod +x $(BIN)/publish.sh
	@$(BIN)/publish.sh $(PUBLISH_ARGS)

.PHONY: publish-dispatch
publish-dispatch: ## Dispatch publish workflow without a version bump.
	@chmod +x $(BIN)/publish.sh
	@$(BIN)/publish.sh --dispatch $(PUBLISH_ARGS)

# ── Release pipeline ──────────────────────────────────────────────────────────
# The branch model lives in .github/WORKFLOW.md. Every CI step is one target
# here, so anything the pipeline does can be reproduced locally.

# The long-lived branch. `dev` rather than `main` — this repo's default branch
# is already dev and two Vercel projects deploy off it.
TRUNK              ?= dev

# Bump used when opening the next release branch.
BUMP               ?= minor

# Commit range for `release-notes`.
RANGE              ?= origin/$(TRUNK)..HEAD

# owner/name. The workflows set this from ${{ github.repository }}; otherwise
# it is derived from the origin remote. `gh` reads this variable natively too.
# (sed uses `,` as its delimiter: a `#` would open a comment, even in $(shell).)
GH_REPO            ?= $(shell git config --get remote.origin.url 2>/dev/null | sed -E 's,.*github\.com[:/],,; s,\.git$$,,')

# Branch and PR-title types accepted by `pr-guard`.
TYPES              := feat|fix|chore|docs|ci|refactor|test|perf|build|style|revert

# Every file carrying the version. The root is authoritative; the three
# workspace members are kept in lockstep because a single self-contained
# corpora-py wheel bundles all of their source.
PYPROJECTS         := pyproject.toml packages/common/pyproject.toml \
                      packages/mcp/pyproject.toml packages/admin/pyproject.toml

# `version = "..."` appears exactly once per file, on the [project] line.
# `target-version` / `python_version` do not match the `^version ` anchor.
pkg_version         = sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml

.PHONY: pkg-version next-version version-set release-notes pr-guard ci pack \
        release-pr release-branch delete-branch tag-release \
        rulesets-diff rulesets-apply

# --- versions ---------------------------------------------------------------

pkg-version: ## Print the version in the root pyproject.toml.
	@$(pkg_version)

next-version: ## Print the version after the newest vX.Y.Z tag (BUMP=major|minor|patch).
	@git tag -l 'v[0-9]*' | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$$' | sed 's/^v//' \
	  | sort -t. -k1,1n -k2,2n -k3,3n | tail -1 \
	  | awk -F. -v b='$(BUMP)' \
	      'BEGIN { maj = 0; min = 0; pat = 0 } { maj = $$1; min = $$2; pat = $$3 } \
	       END { if (b == "major") printf "%d.0.0\n", maj + 1; \
	             else if (b == "patch") printf "%d.%d.%d\n", maj, min, pat + 1; \
	             else printf "%d.%d.0\n", maj, min + 1 }'

# Writes a temp file and moves it rather than using `sed -i`: the in-place flag
# takes a mandatory argument on BSD sed (macOS) and must not have one on GNU
# sed (CI), so no single invocation works in both places.
version-set: ## Write VERSION into every pyproject.toml (env: VERSION).
	@set -eu; : "$${VERSION:?VERSION is required}"; \
	for f in $(PYPROJECTS); do \
	  sed "s/^version = \".*\"/version = \"$$VERSION\"/" "$$f" > "$$f.tmp"; \
	  mv "$$f.tmp" "$$f"; \
	  echo "  $$f is now $$VERSION"; \
	done

release-notes: ## Print a markdown changelog for RANGE (default origin/$(TRUNK)..HEAD).
	@git log --no-merges --reverse --pretty='- %s' $(RANGE) | grep . \
	  || echo '- _Nothing merged yet._'

# --- pull requests ----------------------------------------------------------

# Dependabot opens `dependabot/<ecosystem>/<dep>-<version>` with a "Bump X from
# A to B" title — neither is expressible in the convention, and neither is
# something we can rename. It also targets the default branch, so the bypass
# has to sit above the base switch rather than inside the release/v* case: a
# bot PR lands on the trunk directly and the next release branch, cut from the
# trunk, picks it up. Waving it through beats a permanently-red bot PR.
pr-guard: ## Validate a PR's base, branch name and title (env: BASE, HEAD, TITLE).
	@set -eu; \
	: "$${BASE:?BASE is required}" "$${HEAD:?HEAD is required}"; \
	case "$$HEAD" in \
	dependabot/*) \
	  echo "guard skipped for dependabot: $$HEAD -> $$BASE"; exit 0;; \
	esac; \
	case "$$BASE" in \
	$(TRUNK)) \
	  echo "$$HEAD" | grep -Eq '^release/v[0-9]+\.[0-9]+\.[0-9]+$$' \
	    || { echo "::error::$(TRUNK) only accepts PRs from release/vX.Y.Z (got '$$HEAD')"; exit 1; }; \
	  want="release/v$$($(pkg_version))"; \
	  [ "$$want" = "$$HEAD" ] \
	    || { echo "::error::pyproject.toml declares $$want but the branch is $$HEAD"; exit 1; }; \
	  ;; \
	release/v*) \
	  echo "$$HEAD" | grep -Eq '^($(TYPES))/[a-z0-9][a-z0-9._-]*$$' \
	    || { echo "::error::branch must be <type>/<slug> — one of $(TYPES) (got '$$HEAD')"; exit 1; }; \
	  printf '%s' "$${TITLE-}" | grep -Eq '^($(TYPES))(\([a-z0-9._/-]+\))?!?: .+' \
	    || { echo "::error::PR title must read '<type>: summary' (got '$${TITLE-}')"; exit 1; }; \
	  ;; \
	*) \
	  echo "::error::$$BASE is not a valid base — target $(TRUNK) or release/vX.Y.Z"; exit 1;; \
	esac; \
	echo "guard passed: $$HEAD -> $$BASE"

ci: dep-sync lint-check test ## Everything CI runs on a pull request.

# The single self-contained corpora-py wheel — the same `uv build` the publish
# path runs. If it cannot be produced on the release PR, the post-merge publish
# would fail on the protected trunk instead.
pack: ## Build the publishable wheel (the artifact CI uploads).
	@uv build --wheel --out-dir $(DIST_DIR)
	@ls -lh $(DIST_DIR)/*.whl

release-pr: ## Open or refresh the draft release PR into $(TRUNK) (env: BRANCH).
	@set -eu; \
	branch="$${BRANCH:-$$(git rev-parse --abbrev-ref HEAD)}"; \
	version="$${branch#release/v}"; \
	git fetch --quiet origin \
	  "$(TRUNK):refs/remotes/origin/$(TRUNK)" "$$branch:refs/remotes/origin/$$branch"; \
	body="$$(mktemp)"; \
	{ printf 'Release **v%s**.\n\n## Changes\n\n' "$$version"; \
	  $(MAKE) -s --no-print-directory release-notes RANGE="origin/$(TRUNK)..origin/$$branch"; \
	  printf '\n---\nRefreshed automatically whenever a PR lands on `%s`.\n' "$$branch"; \
	} > "$$body"; \
	num="$$(gh pr list --base $(TRUNK) --head "$$branch" --state open --json number --jq '.[0].number // empty')"; \
	if [ -n "$$num" ]; then \
	  gh pr edit "$$num" --body-file "$$body"; \
	  echo "refreshed release PR #$$num"; \
	else \
	  gh pr create --draft --base $(TRUNK) --head "$$branch" \
	    --title "release: v$$version" --body-file "$$body"; \
	fi; \
	rm -f "$$body"

release-branch: ## Cut release/v<next> from $(TRUNK) with the version bumped (env: VERSION, BUMP).
	@set -eu; \
	git fetch --quiet --force --tags origin "$(TRUNK):refs/remotes/origin/$(TRUNK)"; \
	version="$${VERSION:-$$($(MAKE) -s --no-print-directory next-version)}"; \
	branch="release/v$$version"; \
	if git ls-remote --exit-code --heads origin "$$branch" >/dev/null 2>&1; then \
	  echo "$$branch already exists — nothing to do"; exit 0; \
	fi; \
	git checkout --quiet -B "$$branch" origin/$(TRUNK); \
	$(MAKE) -s --no-print-directory version-set VERSION="$$version"; \
	git add $(PYPROJECTS); \
	git commit --quiet -m "chore(release): open v$$version"; \
	git push --quiet -u origin "$$branch"; \
	echo "opened $$branch"

delete-branch: ## Delete a remote branch, tolerating one already gone (env: BRANCH).
	@set -eu; : "$${BRANCH:?BRANCH is required}"; \
	if gh api -X DELETE "repos/$(GH_REPO)/git/refs/heads/$$BRANCH" >/dev/null 2>&1; then \
	  echo "deleted $$BRANCH"; \
	else \
	  echo "$$BRANCH was already gone"; \
	fi

# Idempotent: a tag already released is skipped, not an error.
#
# Must run with the automation App's token, never GITHUB_TOKEN. The tag this
# pushes is what triggers publish.yml (PyPI) and build-sidecar.yml, and events
# raised by GITHUB_TOKEN do not start workflow runs — both would go silently
# dead.
tag-release: ## Tag HEAD as v<pyproject version> and publish the GitHub Release.
	@set -eu; \
	tag="v$$($(pkg_version))"; \
	if gh api "repos/$(GH_REPO)/git/ref/tags/$$tag" >/dev/null 2>&1; then \
	  echo "$$tag already exists — skipping"; exit 0; \
	fi; \
	gh release create "$$tag" --target "$$(git rev-parse HEAD)" \
	  --title "$$tag" --generate-notes; \
	echo "released $$tag"

# --- repository settings ----------------------------------------------------

rulesets-diff: ## List the rulesets GitHub currently has, by id and name.
	@gh api "repos/$(GH_REPO)/rulesets" --jq '.[] | "\(.id)\t\(.name)"'

# Matched by `.name`, so a file must keep the name of the ruleset already on
# GitHub or a second one is created alongside it.
rulesets-apply: ## Push .github/rulesets/*.json to GitHub (matched by name).
	@set -eu; \
	for f in .github/rulesets/*.json; do \
	  name="$$(jq -r .name "$$f")"; \
	  id="$$(gh api "repos/$(GH_REPO)/rulesets" --jq ".[] | select(.name==\"$$name\") | .id")"; \
	  if [ -n "$$id" ]; then \
	    gh api -X PUT "repos/$(GH_REPO)/rulesets/$$id" --input "$$f" >/dev/null; \
	    echo "updated $$name"; \
	  else \
	    gh api -X POST "repos/$(GH_REPO)/rulesets" --input "$$f" >/dev/null; \
	    echo "created $$name"; \
	  fi; \
	done

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
