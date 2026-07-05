#!/usr/bin/env bash
# PKU Captain — one-shot installer for macOS / Linux.
#
# Creates a project-local virtualenv (.venv) and installs the app plus all
# dependencies into it. No external binaries are needed: PDF rendering is
# in-process (pypdfium2 + Pillow), so there is no poppler/pdftoppm to install.
#
# Re-runnable: an existing .venv is reused and upgraded.
#
#   ./install.sh            # core app
#   ./install.sh --math     # + LaTeX rendering in chat (PyQt6-WebEngine)
#   ./install.sh --dev      # + dev toolchain (pytest, ruff, mypy)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

MIN_MAJOR=3
MIN_MINOR=11

WITH_DEV=0
WITH_MATH=0
for arg in "$@"; do
  case "$arg" in
    --dev)  WITH_DEV=1 ;;
    --math) WITH_MATH=1 ;;
    -h|--help)
      sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "error: unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

# --- locate a Python >= 3.11 --------------------------------------------
find_python() {
  local cand
  for cand in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$cand" >/dev/null 2>&1 && \
       "$cand" -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= ($MIN_MAJOR, $MIN_MINOR) else 1)" 2>/dev/null; then
      echo "$cand"
      return 0
    fi
  done
  return 1
}

PY="$(find_python || true)"
if [ -z "${PY:-}" ]; then
  echo "error: PKU Captain needs Python ${MIN_MAJOR}.${MIN_MINOR}+ on PATH." >&2
  echo "  macOS:  brew install python@3.12" >&2
  echo "  Ubuntu: sudo apt install python3.12 python3.12-venv" >&2
  exit 1
fi
echo "==> using $("$PY" --version) ($(command -v "$PY"))"

# --- create / reuse venv -------------------------------------------------
if [ ! -x ".venv/bin/python" ]; then
  echo "==> creating .venv"
  "$PY" -m venv .venv
else
  echo "==> reusing existing .venv"
fi
VPY=".venv/bin/python"

echo "==> upgrading pip"
"$VPY" -m pip install --quiet --upgrade pip

# --- assemble the extras and install ------------------------------------
EXTRAS=""
[ "$WITH_DEV" = 1 ]  && EXTRAS="${EXTRAS}dev,"
[ "$WITH_MATH" = 1 ] && EXTRAS="${EXTRAS}math,"
TARGET="."
[ -n "$EXTRAS" ] && TARGET=".[${EXTRAS%,}]"

echo "==> installing $TARGET (pulls PyQt6, pypdfium2, Pillow, ...)"
"$VPY" -m pip install -e "$TARGET"

echo
echo "==> done. Launch PKU Captain with:"
echo "     $REPO_ROOT/.venv/bin/python -m src            # offline (no API keys)"
echo "     $REPO_ROOT/.venv/bin/python -m src --online   # online; set keys in the 设置 dialog"
[ "$WITH_MATH" = 0 ] && \
  echo "     (LaTeX in chat bubbles needs --math: re-run ./install.sh --math)"
