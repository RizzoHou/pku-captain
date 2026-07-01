"""macOS desktop notifications for monitor updates.

Platform-isolated and dependency-free: imports only stdlib, so importing this
module on Linux (the pku-captain host) is harmless; constructing MacNotifier off
macOS raises loudly. `osascript` (`display notification`) is the ONLY delivery
mechanism. terminal-notifier was proven dead on macOS 26 — Apple removed its
NSUserNotification path, so it returns rc 0 but delivers nothing, not even to
Notification Center; the daemon must never prefer or depend on it (installing it
would silently kill notifications). Consequence: custom icons and click-to-open
are unavailable — `display notification` always shows the issuing app's icon
("Script Editor") and its clicks aren't actionable. Either would require shipping
a custom signed app (deliberately not done — see git history 2026-06).

Notifications must be posted from within the user's GUI (Aqua) session. A raw
SSH process is *not* in that session and its notifications silently vanish, so
the daemon runs under a LaunchAgent bootstrapped into gui/<uid> (see
macos/install-agent.sh).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# Don't re-nag about SMS re-verification more than once per this window (seconds).
AUTH_NOTIFY_INTERVAL = 3 * 3600

# macOS banners truncate a multi-line body to ~3 lines, so a notification shows
# only the newest few replies and summarizes the rest. (The monitor already
# capped new_comments at COMMENT_CAP; this is the tighter banner-display cap.)
NOTIFY_COMMENT_CAP = 3


def is_macos() -> bool:
    return sys.platform == "darwin"


def _trim(text: str | None, n: int) -> str:
    return (text or "").replace("\n", " ").strip()[:n]


def format_update(u: Any, *, comment_cap: int = NOTIFY_COMMENT_CAP) -> tuple[str, str, str]:
    """(title, subtitle, message) for one monitor.Update — pure, unit-tested.

    End-user-facing copy is Chinese (the users are PKU students). The body shows
    the newest `comment_cap` replies (comments are oldest-first, so the newest sit
    at the tail) and summarizes any remainder; `comment_cap=0` shows all."""
    title = f"树洞 #{u.pid} · +{u.delta} 新回复"
    subtitle = _trim(u.text, 80) or f"{u.old_reply} → {u.new_reply}"
    if u.new_comments:
        shown = u.new_comments[-comment_cap:] if comment_cap else list(u.new_comments)
        lines = [f"[{c.name_tag}] {_trim(c.text, 60)}" for c in shown]
        message = "\n".join(lines)
        hidden = u.delta - len(shown)
        if hidden > 0:
            message += f"\n… 还有 {hidden} 条"
    else:  # comment fetch was disabled or transiently failed → count only
        message = f"{u.old_reply} → {u.new_reply}"
    return title, subtitle, message


def should_notify(state: dict[str, Any], key: str, now: int, interval: int) -> bool:
    """Pure rate-limit check: True if `key` was never recorded or last fired at
    least `interval` seconds ago. Caller records `now` on a True result."""
    last = state.get(key)
    return last is None or now - int(last) >= interval


def _applescript(title: str, subtitle: str, message: str, sound: str | None) -> str:
    """One `display notification` statement, escaping AppleScript string literals.

    Grammar: display notification "<msg>" with title "<t>" subtitle "<s>" sound name "<n>"
    """
    def esc(s: str) -> str:
        # Order matters: double backslashes first, then add our own escapes.
        # A raw newline inside an AppleScript string literal is a syntax error;
        # AppleScript accepts the \n escape, so emit that.
        return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    parts = [f'display notification "{esc(message)}"', f'with title "{esc(title)}"']
    if subtitle:
        parts.append(f'subtitle "{esc(subtitle)}"')
    if sound:
        parts.append(f'sound name "{esc(sound)}"')
    return " ".join(parts)


class MacNotifier:
    def __init__(self, *, state_path: str | Path | None = None,
                 sound: str | None = "default"):
        if not is_macos():
            raise RuntimeError("desktop notifications are macOS-only (osascript)")
        self._osa = shutil.which("osascript")
        if not self._osa:
            raise RuntimeError("osascript not found on PATH")
        self._sound = sound
        self._state_path = Path(state_path) if state_path else None

    # --- public ---------------------------------------------------------------
    def notify_update(self, u: Any) -> None:
        title, subtitle, message = format_update(u)
        self._post(title, subtitle, message)

    def notify_auth_needed(self, msg: str, *, now: int | None = None) -> bool:
        """Post a 'needs SMS re-verification' banner, at most once per
        AUTH_NOTIFY_INTERVAL (persisted). Returns True if it actually posted —
        prevents a fixed-cadence daemon from nagging every tick while locked out."""
        now = int(time.time()) if now is None else now
        state = self._load_state()
        if not should_notify(state, "auth_needed_at", now, AUTH_NOTIFY_INTERVAL):
            return False
        state["auth_needed_at"] = now
        self._save_state(state)  # record before posting: don't retry-spam on a failed post
        self._post("树洞监控：需要重新短信验证", "Treehole monitor paused",
                   f"需要重新短信验证后才能继续监控。\n{_trim(msg, 80)}")
        return True

    # --- mechanism ------------------------------------------------------------
    def _post(self, title: str, subtitle: str, message: str) -> None:
        cmd = [self._osa, "-e", _applescript(title, subtitle, message, self._sound)]
        r = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if r.returncode != 0:  # don't fail the poll, but never fail *silently*
            sys.stderr.write(f"notify: osascript exited {r.returncode}: "
                             f"{(r.stderr or '').strip()}\n")

    # --- rate-limit state -----------------------------------------------------
    def _load_state(self) -> dict[str, Any]:
        if not self._state_path or not self._state_path.exists():
            return {}
        try:
            return json.loads(self._state_path.read_text())
        except (ValueError, OSError):
            return {}

    def _save_state(self, state: dict[str, Any]) -> None:
        if not self._state_path:
            return
        try:
            self._state_path.write_text(json.dumps(state))
        except OSError:
            pass
