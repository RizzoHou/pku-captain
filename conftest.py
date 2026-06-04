"""Front-load this checkout's root onto sys.path so `import src` resolves to the
src/ next to *this* file, not a sibling tree.

Matters in `claude --worktree` worktrees that share the main venv via a symlink:
the shared editable-install pointer (_editable_impl_pku_captain.pth) names the
main checkout, so without this, bare `pytest` in a worktree would silently import
and test the main checkout's src. pytest loads this rootdir conftest before any
test imports src, and inserting at position 0 beats the .pth entry. See CLAUDE.md
"Worktrees". Harmless in the main checkout (its root is already the rootdir).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
