#!/usr/bin/env bash
# Build the curated end-user release bundle -> dist/pku-captain-<version>.zip.
#
# Ships ONLY what install.sh and the running app need: the user README, the
# installer, pyproject, our package (src/), the vendored clients, and the doc
# base. Everything a user never runs is left out — tests/, scripts/, docs/, CI,
# and all Claude/audit artifacts (.claude/, CLAUDE.md, DEVCHANGELOG.md,
# VERIFICATION.md, ARCHITECTURE.html, TASTES/).
#
# Uses `git archive`, so the bundle contains only committed, tracked files at
# HEAD — no __pycache__, no secrets/, no .venv, no local cruft. Commit your
# README/code changes before running, or they won't be in the zip.
#
#   scripts/package_release.sh            # -> dist/pku-captain-<version>.zip
#   scripts/package_release.sh <ref>      # archive a specific tag/commit
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

REF="${1:-HEAD}"
VERSION="$(sed -nE 's/^version *= *"([^"]+)".*/\1/p' pyproject.toml | head -1)"
[ -n "$VERSION" ] || { echo "error: could not read version from pyproject.toml" >&2; exit 1; }

NAME="pku-captain-${VERSION}"
OUT="dist/${NAME}.zip"
mkdir -p dist
rm -f "$OUT"

# Explicit include list — add a runtime path here if the app grows a new one.
git archive --format=zip --prefix="${NAME}/" -o "$OUT" "$REF" \
  README.md \
  install.sh \
  pyproject.toml \
  src \
  vendor \
  doc_base

echo "==> built $OUT ($(du -h "$OUT" | cut -f1)) from $REF"
echo "    upload to a release with:  gh release upload <tag> $OUT"
