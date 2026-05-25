"""Thin subprocess wrapper around the ``pku3b`` CLI.

`pku3b` is an external Rust binary. PKU Captain ships against our fork
at https://github.com/RizzoHou/pku3b (branch
``feat/assignment-list-json-output``), which adds ``--format json`` to
the relevant subcommands so Python consumers get structured data
directly. Install with:

    cargo install --git https://github.com/RizzoHou/pku3b \\
        --branch feat/assignment-list-json-output

This module isolates the subprocess mechanics — locating the
executable, building argv, running with a timeout, and stripping ANSI
colour codes (still useful for ``stderr`` and any legacy text
subcommands) — so the Tool subclasses stay focused on shaping the
JSON response.

It is not itself a Tool subclass; it has no JSON schema and is never
exposed to the LLM. Callers should treat a non-zero return code as a
failure and surface ``stderr``.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_EXECUTABLE = "pku3b"
DEFAULT_TIMEOUT = 60.0
_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_EXECUTABLE = _REPO_ROOT / ".local" / "cargo" / "bin" / "pku3b"

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


class Pku3bNotFoundError(RuntimeError):
    """Raised when the pku3b binary cannot be located on PATH."""


class Pku3bTimeoutError(RuntimeError):
    """Raised when a pku3b subprocess exceeds its timeout."""


@dataclass(frozen=True)
class Pku3bRun:
    """Outcome of a single ``pku3b`` invocation."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from ``pku3b``'s coloured output."""
    return _ANSI_RE.sub("", text)


def resolve_executable(executable: str = DEFAULT_EXECUTABLE) -> str:
    """Locate the pku3b binary; raise :class:`Pku3bNotFoundError` if missing."""
    found = shutil.which(executable)
    if found:
        return found
    if executable == DEFAULT_EXECUTABLE and _LOCAL_EXECUTABLE.exists():
        return str(_LOCAL_EXECUTABLE)
    raise Pku3bNotFoundError(
        f"could not find {executable!r} on PATH or at {_LOCAL_EXECUTABLE}. "
        "Install our fork with: cargo install --git "
        "https://github.com/RizzoHou/pku3b --branch "
        "feat/assignment-list-json-output"
    )


def run_pku3b(
    args: Sequence[str],
    *,
    executable: str = DEFAULT_EXECUTABLE,
    timeout: float = DEFAULT_TIMEOUT,
) -> Pku3bRun:
    """Run ``pku3b`` with the given args and return a :class:`Pku3bRun`.

    ``stdout`` is decoded as UTF-8 and ANSI-stripped before return. A
    non-zero return code is *not* raised — the caller decides how to
    surface it.
    """
    binary = resolve_executable(executable)
    argv = [binary, *args]
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise Pku3bTimeoutError(
            f"pku3b {' '.join(args)} timed out after {timeout}s"
        ) from exc

    return Pku3bRun(
        returncode=proc.returncode,
        stdout=strip_ansi(proc.stdout or ""),
        stderr=strip_ansi(proc.stderr or ""),
    )
