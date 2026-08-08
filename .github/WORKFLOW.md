# Branching and release

Three kinds of branch, and only the first two are long-lived:

| Branch            | Role                    | Protected | Deploys to |
| ----------------- | ----------------------- | --------- | ---------- |
| `main`            | production              | yes       | production |
| `release/vX.Y.Z`  | next / staging          | yes       | staging    |
| `<type>/<slug>`   | development             | no        | preview    |

```
feat/add-parser ──PR──> release/v0.2.0 ──PR──> main ──> tag v0.2.0 ──> PyPI + sidecars
      (deleted on merge)   (deleted on release)         (opens release/v0.3.0)
```

Same model as [corpora-web](https://github.com/exegia/corpora-web), with one
difference: that repo is a deployment, this one is a **package** — merging a
release tags `vX.Y.Z`, and the tag is what drives PyPI, the signed sidecar
bundles, and the GHCR image.

There is no `dev` and no `next`. Development happens on `<type>/<slug>`
branches, and staging is whatever `release/vX.Y.Z` is currently open. See
[Migration](#migration-from-dev--next) — this repo has not moved yet.

## Feature branches

Named `<type>/<slug>` — `feat`, `fix`, `chore`, `docs`, `ci`, `refactor`,
`test`, `perf`, `build`, `style`, `revert`. (Git forbids `:` in a ref name, so
the conventional-commit form lives in the **PR title**: `feat: add parser`.)

Branch off the open release branch and open a PR back into it. While the PR is
a draft only the guard runs; marking it **ready for review** starts the tests
and the AI review, which then re-run on every push. `guard` and `check` are
required, so a red one cannot land.

When it merges the branch deletes itself and the release's draft PR into `main`
is opened or refreshed with a changelog of everything on the branch so far.

Dependabot is the one exception: it opens `dependabot/<ecosystem>/<dep>-<ver>`
with a `Bump X from A to B` title, and neither is renameable. `make pr-guard`
waves those through whichever branch they target.

## Release branches

Named `release/vX.Y.Z`, and always carry that version in **all four**
`pyproject.toml` files (root plus `packages/common`, `packages/mcp`,
`packages/admin`). The root is authoritative; the guard rejects a PR into
`main` where the root and the branch name disagree.

Exactly one is open at a time. It is cut automatically after each release, and
its draft PR into `main` accumulates changes as features land. Marking that PR
ready for review runs the tests plus a real `uv build` of the publishable
wheel, uploaded as an artifact — if the self-contained `corpora-py` wheel
cannot be produced there, the PyPI publish would fail after the merge, on
protected `main`.

This is the staging branch: Vercel gives it a stable branch-alias URL, and
every push also runs the full os × Python matrix, so a macOS-only or 3.14-only
break surfaces while the release is still accumulating rather than on the
release PR.

Its ruleset deliberately omits `creation` and `deletion` rules — `make
release-branch` has to create it and `make delete-branch` has to remove it
after the release.

## `main`

No direct pushes; PRs only from `release/vX.Y.Z`. Merging one creates the
`vX.Y.Z` tag and GitHub Release, deletes the release branch and opens the next
one (minor bump by default).

Everything downstream hangs off that tag: `publish.yml` sends the wheel to
PyPI, `build-sidecar.yml` builds the signed per-platform bundles, and
`docker.yml` pushes the versioned image to GHCR.

## Workflows

| File                | Trigger                      | Does                                  |
| ------------------- | ---------------------------- | ------------------------------------- |
| `pr.yml`            | PR opened / ready / pushed   | `guard`, `check`, `package`, `review` |
| `pr-merged.yml`     | push to `release/v*`         | upserts the release PR                |
| `release.yml`       | PR merged into `main`        | tags, releases, cuts the next release |
| `matrix.yml`        | push to `release/v*`, weekly | os × Python coverage                  |
| `publish.yml`       | push of a `vX.Y.Z` tag       | builds and publishes the wheel to PyPI|
| `build-sidecar.yml` | push of a `vX.Y.Z` tag       | signed, notarized per-platform bundles|
| `docker.yml`        | push to `main` / a tag       | builds and pushes images to GHCR      |
| `automerge.yml`     | Dependabot PR                | enables auto-merge                    |

Every step in the first three is a `make` target, so anything CI does can be
reproduced locally.

### Merge methods differ by level

Feature PRs into a release branch are **squashed** — that is this repo's
convention and it keeps each feature one commit. The release PR into `main` is
a **merge**, and `main.json` enforces that: squashing it would collapse the
whole release into a single commit, and `gh release --generate-notes` would
have nothing to list.

### Deploys are not here

There is exactly one Vercel project — **`corpora-py`** (team `corpora-apps`),
the API at the repo root — and it is wired to Vercel's **Git integration**. It
already gives a preview per branch push and production on the trunk, so there
is no deploy job and no `VERCEL_TOKEN` in this repo. `vercel.yml` remains as a
manual, `workflow_dispatch`-only lever for out-of-band redeploys.

(The `corpora-py-example` project that once served `example/` has been deleted.
A stale `example/.vercel/project.json` may still be lying around locally; it is
gitignored and points at a project that 404s.)

### The tag must not be created by `GITHUB_TOKEN`

`make tag-release` runs with the automation App's token, and that is
load-bearing rather than incidental. Events raised by `GITHUB_TOKEN` do not
start new workflow runs, so a tag pushed with it would leave `publish.yml` and
`build-sidecar.yml` sitting there, never firing, with nothing to indicate the
release had not shipped.

The same rule is why `pr-merged.yml` opens the release PR as the App: a PR
opened by `GITHUB_TOKEN` cannot trigger further workflows, and `guard`,
`check` and `package` are *required* checks on `main` — that PR would never be
mergeable.

### Apply the rulesets before the first release

`.github/rulesets/tags.json` is not cosmetic. The `Publishing` ruleset on
`refs/tags/v*` carries `creation` and `required_signatures` rules, so anything
not on its bypass list is refused when it tries to create `vX.Y.Z` — which is
how the old `smart_version_tagging` push failed silently for months. The
checked-in file is the live ruleset plus the automation App
(`corpora-ui-automation`, Integration `4425676`) as a bypass actor. Without
that entry `make tag-release` cannot tag, and nothing downstream of the tag
ships.

```bash
make rulesets-diff     # what GitHub has now
make rulesets-apply    # push all three files
```

## Migration from `dev` + `next`

This repo currently has `dev` (default) and `next` (the API project's Vercel
production branch), and **no `main`**. Until these steps are done the pipeline
above does not work: `pr.yml` and `release.yml` key on `main`, which does not
exist, so nothing fires.

1. **Create `main` from `dev`.** `dev` carries the latest work.
   ```bash
   git push origin dev:refs/heads/main
   ```
2. **Make `main` the default branch** (Settings → General). Dependabot and new
   PRs retarget automatically.
3. **Repoint the `corpora-py` Vercel project's production branch to `main`**
   (Project → Settings → Git → Production Branch, currently `next`). Do this
   *before* step 5 — `next` is live production for the API today, and deleting
   it while it is still the production branch is the one ordering that bites.
4. **Apply the rulesets**, then delete the superseded one:
   ```bash
   make rulesets-apply
   gh api -X DELETE repos/exegia/corpora-py/rulesets/18169832  # "Protect dev and next branches"
   ```
   `make rulesets-apply` matches by `.name`, so it creates `Protect main
   branch` and `Protect release branches` rather than updating the old one —
   which is why the old one has to go explicitly.
5. **Delete `dev` and `next`** once production is confirmed on `main`.
6. **Bootstrap the first release branch** (below).

## Bootstrap and manual operations

There is no release branch to start from. Run the **Release** workflow manually
(`Actions → Release → Run workflow`, pick a bump) — the release job skips and
the next-release job opens the branch. Locally:

```bash
make release-branch BUMP=minor
```

The newest tag is `v0.1.3`, so the first release branch is `release/v0.2.0`
(or `release/v0.1.4` with `BUMP=patch`).

Other useful targets:

```bash
make ci                            # what CI runs on a PR
make pack                          # build the publishable wheel
make pkg-version                   # the version in the root pyproject.toml
make next-version BUMP=patch       # what the next release would be called
make release-notes RANGE=origin/main..HEAD
make rulesets-diff                 # rulesets GitHub actually has
make rulesets-apply                # push .github/rulesets/*.json
```

`make tag-release` is idempotent — a tag already released is skipped, not an
error.

Everything is parameterised on `TRUNK`, so a one-off against a different trunk
is `make pr-guard TRUNK=some-branch ...`.

## Secrets

| Name                                               | Where            | Used by                     |
| -------------------------------------------------- | ---------------- | --------------------------- |
| `AUTOMATION_APP_ID` / `AUTOMATION_APP_PRIVATE_KEY` | **organisation** | opening PRs, branches, tags |
| `CLAUDE_CODE_OAUTH_TOKEN`                          | **organisation** | the AI review (optional)    |

All three are **organisation** secrets on `exegia`, inherited by this repo —
`gh api repos/exegia/corpora-py/actions/secrets` returns an empty list and is
not evidence they are missing; use `gh api orgs/exegia/actions/secrets`. The
backing App is `corpora-ui-automation` (Integration `4425676`), installed
org-wide with `contents: write` + `pull_requests: write`.

PyPI needs no secret — `publish.yml` uses OIDC trusted publishing against the
`pypi` environment. **That binding names the workflow file**, so renaming
`publish.yml` breaks it until the publisher is re-pointed on PyPI.

Without `CLAUDE_CODE_OAUTH_TOKEN` the review job skips with a note in the job
summary rather than failing. The automation App is **not** optional:
`pr-merged.yml`, `release` and `next-release` all fail at their first step
without it.
