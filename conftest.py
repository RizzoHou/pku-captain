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

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)

# Bridge the newly-vendored `pypku3b` until the main checkout is reinstalled
# (`pip install -e .`): the shared venv's editable install has not yet picked up
# its hatchling packages entry, and worktrees must not `pip install` into the
# shared venv. Once main is reinstalled this resolves via the .pth too, so the
# insert is a harmless duplicate. The other vendored libs are already installed.
sys.path.insert(0, os.path.join(_ROOT, "vendor", "pypku3b", "src"))
