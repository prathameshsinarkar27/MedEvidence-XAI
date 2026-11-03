#!/usr/bin/env bash
# Simple pre-release hygiene check: fails if a real .env or obvious secret patterns are present.
# Usage: scripts/check_secrets.sh   (run from anywhere)
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 2
status=0

if [ -f .env ]; then
  echo "FAIL: .env exists (must not be committed or zipped)"; status=1
fi

EXCLUDES=(--exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=.git --exclude-dir=dist
          --exclude-dir=__pycache__ --exclude-dir=logs --exclude=check_secrets.sh --exclude=.env.example)

# Private keys, cloud/API token shapes
if grep -rIEn "${EXCLUDES[@]}" \
   -e "-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----" \
   -e "AKIA[0-9A-Z]{16}" \
   -e "sk-[A-Za-z0-9]{20,}" \
   -e "ghp_[A-Za-z0-9]{30,}" . ; then
  echo "FAIL: possible secret token found"; status=1
fi

# URLs with an inline password, e.g. scheme://user:password@host
# Explicit placeholders (user:PASSWORD@, :change_me...@) and lines marked `allowlist-secret` are ignored.
hits=$(grep -rIEn "${EXCLUDES[@]}" -e "://[^/[:space:]:@]+:[^/[:space:]@]+@" . \
       | grep -vE ":(password|pass|PASSWORD|change_me[A-Za-z_]*)@" | grep -v "allowlist-secret" || true)
if [ -n "$hits" ]; then
  echo "$hits"; echo "FAIL: connection string with embedded credentials found"; status=1
fi

[ $status -eq 0 ] && echo "OK: no secrets detected"
exit $status
