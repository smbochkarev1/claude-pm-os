#!/usr/bin/env bash
# Leak guard — fail if secrets or personal data reached the tree that's about to
# be shared/published. Run before committing or cutting a distribution.
#
# The rule: code and committed config must be impersonal. Identity, ids and
# tokens live ONLY in the user's local .env / *.yaml (git-ignored), never in the
# repo. This script greps the repo (excluding venv/git/caches) for tell-tale
# secret shapes and any values you add to LEAK_PATTERN below.
#
# Usage:  bash scripts/build_dist.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Generic secret shapes. Extend LEAK_PATTERN with your own handle/ids so an
# accidental paste of real data is caught here rather than after publishing.
LEAK_PATTERN='sk-ant-[A-Za-z0-9]{20}|sk-[A-Za-z0-9]{20}|AA[A-Za-z0-9_-]{30}|xox[baprs]-[A-Za-z0-9-]{10}|ghp_[A-Za-z0-9]{20}|-----BEGIN [A-Z ]*PRIVATE KEY-----'

# Files that legitimately show placeholder shapes (docs/examples) are excluded.
EXCLUDES=(--exclude-dir=.git --exclude-dir=.venv --exclude-dir=venv
          --exclude-dir=__pycache__ --exclude-dir=node_modules
          --exclude-dir=cache --exclude-dir=snapshots --exclude-dir=debriefs)

echo "[leak-guard] scanning $ROOT ..."
if grep -rInE "${EXCLUDES[@]}" "$LEAK_PATTERN" "$ROOT" 2>/dev/null; then
    echo "" >&2
    echo "ERROR: possible secret/personal data above. Move it to your local .env" >&2
    echo "(git-ignored) and keep the repo impersonal." >&2
    exit 1
fi

# Real .env must never be tracked.
if git -C "$ROOT" ls-files --error-unmatch .env >/dev/null 2>&1; then
    echo "ERROR: .env is tracked by git — it must be git-ignored." >&2
    exit 1
fi

echo "[leak-guard] clean."
