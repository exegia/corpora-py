#!/usr/bin/env python3
"""Publish a new exegia release via the GitHub Actions publish workflow.

Two modes:

  tag (default)
    Bumps the version in pyproject.toml and src/exegia/__init__.py, commits,
    creates a vX.Y.Z tag, and pushes — the "Publish" workflow picks it up
    automatically via its tag trigger.

  dispatch (--dispatch)
    Triggers a workflow_dispatch event directly on a branch without touching
    the version. Useful for re-running a failed publish or testing a build.

Note: PRs merged to master/main trigger an automatic patch bump and publish
via the "Publish" workflow — you do not need this script for day-to-day
releases. Use it when you want explicit control over the version or type.

Usage:
    uv run scripts/publish.py                    # bump patch, commit, tag, push
    uv run scripts/publish.py patch              # same
    uv run scripts/publish.py minor              # bump minor, tag, push
    uv run scripts/publish.py major              # bump major, tag, push
    uv run scripts/publish.py 1.2.3              # explicit version, tag, push
    uv run scripts/publish.py --dispatch         # trigger workflow_dispatch on master (build only)
    uv run scripts/publish.py --dispatch --publish   # same, and upload to PyPI
    uv run scripts/publish.py --dispatch --ref some-branch

Required for --dispatch (or in .env.publish):
    GITHUB_TOKEN   personal access token with repo + workflow scopes
    Create at https://github.com/settings/tokens
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
VERSION_FILE = ROOT / "src" / "exegia" / "__init__.py"
REPO = "Mannydefreitas7/exegia-api-py"
WORKFLOW_FILE = "publish.yml"


# ── helpers ───────────────────────────────────────────────────────────────────


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=False)
    if check and result.returncode != 0:
        sys.exit(result.returncode)
    return result


def current_version() -> str:
    text = PYPROJECT.read_text()
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not m:
        sys.exit("error: could not find version in pyproject.toml")
    return m.group(1)


def bump(version: str, part: str) -> str:
    major, minor, patch = (int(x) for x in version.split("."))
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def set_version(old: str, new: str) -> None:
    for path in (PYPROJECT, VERSION_FILE):
        text = path.read_text()
        updated = text.replace(f'"{old}"', f'"{new}"', 1)
        if updated == text:
            sys.exit(f"error: version string not found in {path}")
        path.write_text(updated)
        print(f"  updated {path.relative_to(ROOT)}")


def resolve_new_version(part_or_version: str) -> str:
    if part_or_version in ("patch", "minor", "major"):
        return bump(current_version(), part_or_version)
    if not re.fullmatch(r"\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?", part_or_version):
        sys.exit(
            f"error: '{part_or_version}' is not a valid version "
            "(expected X.Y.Z or patch/minor/major)"
        )
    return part_or_version


# ── tag mode ──────────────────────────────────────────────────────────────────


def ensure_clean_tree() -> None:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    dirty = [l for l in result.stdout.splitlines() if not l.startswith("?")]
    if dirty:
        sys.exit(
            "error: working tree has uncommitted changes. "
            "Commit or stash them before publishing."
        )


def commit_and_tag(version: str) -> str:
    tag = f"v{version}"
    run(["git", "add", str(PYPROJECT), str(VERSION_FILE)])
    run(["git", "commit", "-m", f"chore: bump version to {version}"])
    run(["git", "tag", tag])
    return tag


def push_tag(tag: str) -> None:
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    ).stdout.strip()
    run(["git", "push", "origin", branch])
    run(["git", "push", "origin", tag])
    print(f"\nTag {tag} pushed. GitHub Actions will build and publish the package.")
    print(f"Track progress at https://github.com/{REPO}/actions")


def tag_release(version_arg: str) -> None:
    ensure_clean_tree()
    old = current_version()
    new = resolve_new_version(version_arg)
    print(f"Bumping version: {old} → {new}")
    set_version(old, new)
    tag = commit_and_tag(new)
    push_tag(tag)


# ── dispatch mode ─────────────────────────────────────────────────────────────


def github_token() -> str:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        env_publish = ROOT / ".env.publish"
        if env_publish.exists():
            for line in env_publish.read_text().splitlines():
                if line.startswith("GITHUB_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
    if not token:
        sys.exit(
            "error: GITHUB_TOKEN is required for --dispatch.\n"
            "Set it in your environment or in .env.publish.\n"
            "Create a token at https://github.com/settings/tokens "
            "(repo + workflow scopes)."
        )
    return token


def dispatch_workflow(publish: bool, ref: str = "master") -> None:
    token = github_token()
    url = (
        f"https://api.github.com/repos/{REPO}/actions/workflows"
        f"/{WORKFLOW_FILE}/dispatches"
    )
    payload = {"ref": ref, "inputs": {"publish": str(publish).lower()}}
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="POST",
    )
    print(f"Dispatching '{WORKFLOW_FILE}' on '{ref}' (publish={publish})...")
    try:
        with urllib.request.urlopen(req) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        sys.exit(f"GitHub API error {e.code}: {e.read().decode()}")
    print(f"Workflow dispatched. Track progress at https://github.com/{REPO}/actions")


# ── main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "version",
        nargs="?",
        default="patch",
        metavar="patch|minor|major|X.Y.Z",
        help="Version bump type or explicit version (default: patch). "
             "Ignored when --dispatch is used.",
    )
    parser.add_argument(
        "--dispatch",
        action="store_true",
        help="Trigger workflow_dispatch directly instead of pushing a tag. "
             "Does not bump the version.",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Only valid with --dispatch. Passes publish=true to the workflow "
             "(build and upload to PyPI).",
    )
    parser.add_argument(
        "--ref",
        default="master",
        metavar="BRANCH",
        help="Branch to dispatch on (--dispatch only, default: master).",
    )
    args = parser.parse_args()

    if args.publish and not args.dispatch:
        parser.error("--publish requires --dispatch")

    if args.dispatch:
        dispatch_workflow(publish=args.publish, ref=args.ref)
    else:
        tag_release(args.version)


if __name__ == "__main__":
    main()
