#!/usr/bin/env bash
#
# git_work.sh
# Shell equivalent of scripts/git_work.py
#
# Git workflow helper:
#   - Creates a typed branch (fix/test/doc/feature/cicd/refactor/chore-YYYY-MM-DD)
#   - Commits staged changes
#   - Pushes and creates a draft PR (via gh if available)
#
# Usage:
#   git add ...
#   ./scripts/git_work.sh "my commit message"
#   # or without message to be prompted
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

ALLOWED_TYPES=(fix test doc feature cicd refactor chore)
REPO_OWNER="exegia"
DEFAULT_BRANCH="main"

run() {
  # Simple runner that prints and executes
  echo "  $ $*"
  (cd "$ROOT" && "$@")
}

run_capture() {
  (cd "$ROOT" && "$@")
}

get_staged_files() {
  run_capture git diff --cached --name-only
}

main() {
  # Prevent recursion if called from hook
  if [[ "${GIT_WORK_FLOW:-}" == "1" ]]; then
    return
  fi

  # 1. Check for staged changes
  if [[ -z "$(get_staged_files)" ]]; then
    echo "❌ No staged changes found. Please 'git add' your changes first."
    exit 1
  fi

  # 2. Get input
  local raw_msg=""
  if [[ $# -gt 0 ]]; then
    raw_msg="$1"
  else
    read -r -p "Commit message: " raw_msg || true
  fi

  raw_msg="$(echo "$raw_msg" | xargs)"  # trim
  if [[ -z "$raw_msg" ]]; then
    echo "❌ Commit message is required."
    exit 1
  fi

  # 3. Parse Type and Title
  local work_type=""
  local clean_title=""

  if [[ "$raw_msg" =~ ^([a-zA-Z]+):\ *(.*) ]]; then
    work_type="${BASH_REMATCH[1],,}"
    clean_title="${BASH_REMATCH[2]}"
  else
    echo "Available types: ${ALLOWED_TYPES[*]}"
    read -r -p "Select type (default 'feature'): " work_type || true
    work_type="${work_type,,}"
    [[ -z "$work_type" ]] && work_type="feature"
    clean_title="$raw_msg"
  fi

  if [[ ! " ${ALLOWED_TYPES[*]} " =~ \ ${work_type}\  ]]; then
    echo "⚠️  Warning: '${work_type}' is not a standard type."
  fi

  # 4. Generate metadata
  local date_str
  date_str=$(date +%m-%d-%Y)
  local branch_name="${work_type}-${date_str}"

  # Ensure branch uniqueness
  local existing
  existing=$(run_capture git branch --list)

  if echo "$existing" | grep -qE "(^| )${branch_name}( |$)"; then
    local suffix=1
    while echo "$existing" | grep -qE "(^| )${branch_name}-${suffix}( |$)"; do
      ((suffix++))
    done
    branch_name="${branch_name}-${suffix}"
  fi

  echo "🚀 Preparing workflow for: ${branch_name}"

  # 5. Execute Git flow
  echo "  - Creating branch..."

  # Determine base branch
  local base
  base=$(run_capture git remote show origin 2>/dev/null | grep 'HEAD branch' | awk '{print $NF}' || true)
  [[ -z "$base" ]] && base="$DEFAULT_BRANCH"

  run git checkout -b "$branch_name"

  echo "  - Committing..."
  local full_commit_msg="${work_type}: ${clean_title}"
  run git commit --no-verify -m "$full_commit_msg"

  echo "  - Pushing to remote..."
  run git push -u origin "$branch_name"

  # 6. Create Draft PR using GitHub CLI
  local pr_title="${clean_title} - ${work_type}"
  echo "  - Creating Draft PR: ${pr_title}"

  if command -v gh >/dev/null 2>&1; then
    # Determine base again for PR
    base=$(run_capture git remote show origin 2>/dev/null | grep 'HEAD branch' | awk '{print $NF}' || true)
    [[ -z "$base" ]] && base="$DEFAULT_BRANCH"

    # gh pr create ...
    # We quote carefully
    if gh pr create \
        --draft \
        --title "$pr_title" \
        --body "Automated PR created on ${date_str}" \
        --assignee "$REPO_OWNER" \
        --reviewer "github-copilot" \
        --base "$base"; then
      echo
      echo "✅ Success! PR created and assigned to ${REPO_OWNER} with Copilot review."
    else
      echo
      echo "⚠️  PR creation command failed."
    fi
  else
    echo
    echo "⚠️  PR creation failed. Ensure 'gh' CLI is installed and authenticated."
  fi
}

main "$@"
