"""Strip known secret values from text before it can leave the process.

Credentials we inject into a subprocess (P-Lib ``PLIB_EMAIL``/``PLIB_PASSWORD``
env) or hand to a library (treehole IAAA id/password) can be echoed back in
stderr or exception text on an auth failure. That text becomes a
``ToolResult.error``, which ``Agent.turn()`` writes into the conversation — so
it is shipped to the LLM on the next request and persisted to
``data/sessions/*.json``. Redacting the known secret values at the tool
boundary keeps a credential out of that path.

This only covers secrets *we* hold. pku3b's portal password lives in pku3b's
own ``cfg.toml`` and never enters this process, so we cannot redact it; treat
any pku3b stderr as out of our control.
"""

from __future__ import annotations

from collections.abc import Iterable

REDACTED = "***REDACTED***"


def redact(text: str, secrets: Iterable[str], placeholder: str = REDACTED) -> str:
    """Replace every occurrence of each secret in ``text`` with ``placeholder``.

    Fails safe: an empty/whitespace secret is skipped (replacing the empty
    string would shred the whole text), but a short real secret is still
    redacted — over-redaction is the safe direction, under-redaction leaks.
    """
    if not text:
        return text
    result = text
    for secret in secrets:
        if secret and secret.strip():
            result = result.replace(secret, placeholder)
    return result
