# Branching and release

Two long-lived things: `dev` and the tags. Everything else is temporary.

```
feat/add-parser ──PR──> release/v0.2.0 ──PR──> dev ──> tag v0.2.0 ──> PyPI + sidecars
      (deleted on merge)   (deleted on release)        (opens release/v0.3.0)
```

Same model as [corpora-web](https://github.com/exegia/corpora-web), with two differences. That repo is a deployment;
this one is a **package** — merging a release tags `vX.Y.Z`, and the tag is what drives PyPI and the signed sidecar
bundles. And the trunk is `dev`, not `main`: `main` has never existed here, and
`dev` is already the default branch.

## Feature branches

Named `<type>/<slug>` — `feat`, `fix`, `chore`, `docs`, `ci`, `refactor`,
`test`, `perf`, `build`, `style`, `revert`. (Git forbids `:` in a ref name, so the conventional-commit form lives in the
**PR title**: `feat: add parser`.)

Branch off the open release branch and open a PR back into it. While the PR is a draft only the guard runs; marking it
**ready for review** starts the tests and the AI review, which then re-run on every push.

When it merges the branch deletes itself and the release's draft PR into `dev`
is opened or refreshed with a changelog of everything on the branch so far.

Dependabot is the one exception: it opens `dependabot/<ecosystem>/<dep>-<ver>`
against the default branch with a `Bump X from A to B` title, and neither is renameable. `make pr-guard` waves those
through, they land on `dev` directly, and the next release branch — cut from `dev` — picks them up.

## Release branches

Named `release/vX.Y.Z`, and always carry that version in **all four**
`pyproject.toml` files (root plus `packages/common`, `packages/mcp`,
`packages/admin`). The root is authoritative; the guard rejects a PR into `dev`
where the root and the branch name disagree.

Exactly one is open at a time. It is cut automatically after each release, and its draft PR into `dev` accumulates
changes as features land. Marking that PR ready for review runs the tests plus a real `uv build` of the publishable
wheel, uploaded as an artifact — if the self-contained `corpora-py` wheel cannot be produced there, the PyPI publish
would fail after the merge, on protected `dev`.

Pushes to a release branch also run the full os × Python matrix, so a macOS-only or 3.14-only break surfaces while the
release is still accumulating rather than on the release PR.

## `dev`

No direct pushes; PRs only from `release/vX.Y.Z` (and Dependabot). Merging one creates the `vX.Y.Z` tag and GitHub
Release, deletes the release branch and opens the next one (minor bump by default).

Everything downstream hangs off that tag: `publish.yml` sends the wheel to PyPI, `build-sidecar.yml` builds the signed
per-platform bundles, and
`docker.yml` pushes the versioned image to GHCR.

## Workflows

| File                | Trigger                      | Does                                   |
|---------------------|------------------------------|----------------------------------------|
| `pr.yml`            | PR opened / ready / pushed   | `guard`, `check`, `package`, `review`  |
| `pr-merged.yml`     | push to `release/v*`         | upserts the release PR                 |
| `release.yml`       | PR merged into `dev`         | tags, releases, cuts the next release  |
| `matrix.yml`        | push to `release/v*`, weekly | os × Python coverage                   |
| `publish.yml`       | push of a `vX.Y.Z` tag       | builds and publishes the wheel to PyPI |
| `build-sidecar.yml` | push of a `vX.Y.Z` tag       | signed, notarized per-platform bundles |
| `docker.yml`        | push to `dev` / a tag        | builds and pushes images to GHCR       |
| `automerge.yml`     | Dependabot PR                | enables auto-merge                     |

Every step in the first three is a `make` target, so anything CI does can be reproduced locally.

### Deploys are not here

Both Vercel projects — the API at the repo root and the web example under
`example/` — are wired to Vercel's **Git integration**. It already gives a preview per release-branch push and
production on the trunk, so there is no deploy job and no `VERCEL_TOKEN` in this repo. `vercel.yml` remains as a manual,
`workflow_dispatch`-only lever for out-of-band redeploys.

> **Open item.** The API project's production branch is still `next`, a
> leftover from the previous `dev → next` scheme. Until it is repointed to
> `dev` in the Vercel dashboard, merging a release does not update API
> production. `next` has no role in this model and should be retired.

### Merge methods differ by level

Feature PRs into a release branch are **squashed** — that is this repo's convention and it keeps each feature one
commit. The release PR into `dev` is a **merge**, and `dev.json` enforces that: squashing it would collapse the whole
release into a single commit, and `gh release --generate-notes` would have nothing to list.

### Apply the rulesets before the first release

`.github/rulesets/tags.json` is not cosmetic. The `Publishing` ruleset on
`refs/tags/v*` carries `creation` and `required_signatures` rules, so anything not on its bypass list is refused when it
tries to create `vX.Y.Z` — which is how the old `smart_version_tagging` push failed silently for months. The checked-in
file is the live ruleset plus the automation App (`corpora-ui-automation`, Integration `4425676`) as a bypass actor.
Without that entry `make tag-release` cannot tag, and nothing downstream of the tag ships.

`dev.json` also drops the `update` rule the current ruleset has on `dev`. That rule is what makes `gh pr merge` fail
with "base branch policy prohibits the merge" and forces `--admin` today.

```bash
make rulesets-diff     # what GitHub has now
make rulesets-apply    # push both files
```

### The tag must not be created by `GITHUB_TOKEN`

`make tag-release` runs with the automation App's token, and that is load- bearing rather than incidental. Events raised
by `GITHUB_TOKEN` do not start new workflow runs, so a tag pushed with it would leave `publish.yml` and
`build-sidecar.yml` sitting there, never firing, with nothing to indicate the release had not shipped.

The same rule is why `pr-merged.yml` opens the release PR as the App: a PR opened by `GITHUB_TOKEN` cannot trigger
further workflows, and `guard`,
`check` and `package` are *required* checks on `dev` — that PR would never be mergeable.

## Bootstrap and manual operations

There is no release branch to start from. Run the **Release** workflow manually (`Actions → Release → Run workflow`,
pick a bump) — the release job skips and the next-release job opens the branch. Locally:

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
make release-notes RANGE=origin/dev..HEAD
make rulesets-diff                 # rulesets GitHub actually has
make rulesets-apply                # push .github/rulesets/*.json
```

`make tag-release` is idempotent — a tag already released is skipped, not an error. `make rulesets-apply` matches by
`.name`, so each file keeps the name of the ruleset already on GitHub (`Protect dev and next branches`, `Publishing`)
or a second one is created alongside it. `dev.json` scopes its ruleset to
`refs/heads/dev` only; once `next` is retired, rename it in the dashboard and in the file together.

## Secrets

| Name                                               | Where      | Used by                     |
|----------------------------------------------------|------------|-----------------------------|
| `AUTOMATION_APP_ID` / `AUTOMATION_APP_PRIVATE_KEY` | repository | opening PRs, branches, tags |
| `CLAUDE_CODE_OAUTH_TOKEN`                          | repository | the AI review (optional)    |

PyPI needs no secret — `publish.yml` uses OIDC trusted publishing against the
`pypi` environment. **That binding names the workflow file**, so renaming
`publish.yml` breaks it until the publisher is re-pointed on PyPI.

Without `CLAUDE_CODE_OAUTH_TOKEN` the review job skips with a note in the job summary rather than failing. The
automation App is **not** optional:
`pr-merged.yml`, `release` and `next-release` all fail at their first step without it, and neither secret exists on this
repository yet.
