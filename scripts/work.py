#!/usr/bin/env python3
import datetime
import os
from pathlib import Path
import re
import subprocess
import sys

# Configuration
ALLOWED_TYPES = ["fix", "test", "doc", "feature", "cicd", "refactor", "chore"]
REPO_OWNER = "mannydefreitas7"
DEFAULT_BRANCH = "master"
ROOT = Path(__file__).resolve().parent.parent


def run(cmd, check=True):
    """Utility to run shell commands and return output."""
    result = subprocess.run(
        cmd, shell=True, text=True, capture_output=True, cwd=ROOT
    )
    if check and result.returncode != 0:
        print(f"Error: Command failed -> {cmd}")
        if result.stderr:
            print(result.stderr.strip())
        sys.exit(result.returncode)
    return result.stdout.strip()


def get_staged_files():
    return run("git diff --cached --name-only")


def main():
    # 0. Prevent recursion if called from hook
    if os.environ.get("GIT_WORK_FLOW"):
        return

    # 1. Check for staged changes
    if not get_staged_files():
        print("❌ No staged changes found. Please 'git add' your changes first.")
        sys.exit(1)

    # 2. Get input (from args or prompt)
    raw_msg = sys.argv[1] if len(sys.argv) > 1 else input("Commit message: ").strip()
    if not raw_msg:
        print("❌ Commit message is required.")
        sys.exit(1)

    # 3. Parse Type and Title
    # Try to extract type from "type: message" format
    match = re.match(r"^(\w+):\s*(.*)", raw_msg)
    if match:
        work_type = match.group(1).lower()
        clean_title = match.group(2)
    else:
        print(f"Available types: {', '.join(ALLOWED_TYPES)}")
        work_type = (
            input("Select type (default 'feature'): ").strip().lower() or "feature"
        )
        clean_title = raw_msg

    if work_type not in ALLOWED_TYPES:
        print(f"⚠️  Warning: '{work_type}' is not a standard type.")

    # 4. Generate metadata
    date_str = datetime.datetime.now().strftime("%m-%d-%Y")
    # Branch names cannot have spaces; using hyphen as requested/implied
    branch_name = f"{work_type}-{date_str}"

    # Ensure branch uniqueness
    existing = run("git branch --list")
    if branch_name in existing:
        suffix = 1
        while f"{branch_name}-{suffix}" in existing:
            suffix += 1
        branch_name = f"{branch_name}-{suffix}"

    print(f"🚀 Preparing workflow for: {branch_name}")

    # 5. Execute Git flow
    print(f"  - Creating branch...")
    # Determine base branch before switching
    base = run("git remote show origin | grep 'HEAD branch' | cut -d' ' -f5", check=False) or DEFAULT_BRANCH
    run(f"git checkout -b {branch_name}")

    print(f"  - Committing...")
    full_commit_msg = f"{work_type}: {clean_title}"
    run(f'git commit --no-verify -m "{full_commit_msg}"')

    print(f"  - Pushing to remote...")
    run(f"git push -u origin {branch_name}")

    # 6. Create Draft PR using GitHub CLI
    pr_title = f"{clean_title} - {work_type}"
    print(f"  - Creating Draft PR: {pr_title}")

    try:
        # Check if gh is installed
        run("gh --version")

        # Determine base branch for the PR
        base = (
            run(
                "git remote show origin | grep 'HEAD branch' | cut -d' ' -f5",
                check=False,
            )
            or DEFAULT_BRANCH
        )

        # Construct GH command
        # Note: --reviewer github-copilot triggers the Copilot review
        gh_cmd = [
            "gh",
            "pr",
            "create",
            "--draft",
            "--title",
            f'"{pr_title}"',
            "--body",
            f'"Automated PR created on {date_str}"',
            "--assignee",
            REPO_OWNER,
            "--reviewer",
            "github-copilot",
            "--base",
            base,
        ]

        run(" ".join(gh_cmd))
        print(
            f"\n✅ Success! PR created and assigned to {REPO_OWNER} with Copilot review."
        )
    except Exception:
        print(
            "\n⚠️  PR creation failed. Ensure 'gh' CLI is installed and authenticated."
        )


if __name__ == "__main__":
    main()
