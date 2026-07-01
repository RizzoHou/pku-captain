"""pku-dean-cli — fetch public resources from dean.pku.edu.cn.

The package is usable two ways:

* as a CLI (``dean ...``), emitting a stable JSON envelope under ``--format json``;
* as a library, importing :mod:`dean.resources` and a :class:`dean.client.DeanClient`.

Only public resources are covered (no IAAA login required). See :mod:`dean.auth`
for the authentication hook left for future, gated content.
"""

from .client import DeanClient
from .errors import DeanError

__version__ = "0.1.0"
__all__ = ["DeanClient", "DeanError", "__version__"]
