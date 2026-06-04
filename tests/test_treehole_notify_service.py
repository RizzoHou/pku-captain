"""Unit coverage for TreeholeNotificationService.

launchctl mutates real per-user state, so it is never invoked here: a fake
`runner` records the commands and the service is pinned to a fake `darwin`
platform with temp directories. This proves the pure parts — plist contents,
the launchctl sequence and ordering, interval persistence/validation, status
transitions, and off-macOS gating — without touching the host's LaunchAgents.
A real launchctl smoke is done manually on macOS, not in CI.
"""

from __future__ import annotations

import plistlib
from dataclasses import dataclass, field
from pathlib import Path

from src.tools.treehole_updates import (
    DEFAULT_NOTIFY_INTERVAL,
    MIN_NOTIFY_INTERVAL,
    TreeholeNotificationService,
)


@dataclass
class FakeRunner:
    """Records launchctl invocations; returns a configurable exit code."""

    returncode: int = 0
    stderr: str = ""
    calls: list[list[str]] = field(default_factory=list)

    def __call__(self, cmd: list[str]) -> FakeRunner._Result:
        self.calls.append(list(cmd))
        return self._Result(self.returncode, self.stderr)

    @dataclass
    class _Result:
        returncode: int
        stderr: str


def _service(
    tmp_path: Path,
    *,
    runner: FakeRunner | None = None,
    platform_name: str = "darwin",
    with_binary: bool = True,
    with_session: bool = False,
) -> TreeholeNotificationService:
    secrets = tmp_path / "secrets" / "treehole"
    secrets.mkdir(parents=True, exist_ok=True)
    if with_session:
        (secrets / "session.json").write_text("{}")
    bin_path = tmp_path / "treehole"
    if with_binary:
        bin_path.write_text("#!/bin/sh\n")
        bin_path.chmod(0o755)
    return TreeholeNotificationService(
        secrets_dir=secrets,
        treehole_bin=bin_path,
        state_path=tmp_path / "state.json",
        settings_path=tmp_path / "settings.json",
        log_dir=tmp_path / "logs",
        launch_agents_dir=tmp_path / "LaunchAgents",
        runner=runner or FakeRunner(),
        platform_name=platform_name,
        uid=501,
    )


def test_enable_writes_plist_and_runs_launchctl_in_order(tmp_path: Path) -> None:
    runner = FakeRunner()
    svc = _service(tmp_path, runner=runner)

    result = svc.enable(300)

    assert result["ok"] is True
    assert result["interval"] == 300
    plist_path = tmp_path / "LaunchAgents" / f"{svc.LABEL}.plist"
    assert plist_path.exists()

    plist = plistlib.loads(plist_path.read_bytes())
    assert plist["Label"] == svc.LABEL
    assert plist["StartInterval"] == 300
    assert plist["RunAtLoad"] is True
    args = plist["ProgramArguments"]
    assert args[0] == str(tmp_path / "treehole")
    assert "--secrets-dir" in args and "--notify" in args and "monitor" in args
    assert args[args.index("--state") + 1] == str(tmp_path / "state.json")

    verbs = [c[1] for c in runner.calls]
    assert verbs == ["bootout", "bootstrap", "enable", "kickstart"]
    # All targets address our dedicated label in the user's GUI domain.
    assert all(f"gui/501/{svc.LABEL}" in c or "gui/501" in c for c in runner.calls)


def test_enable_aborts_with_message_on_launchctl_failure(tmp_path: Path) -> None:
    runner = FakeRunner(returncode=5, stderr="Bootstrap failed")
    svc = _service(tmp_path, runner=runner)

    result = svc.enable(60)

    assert result["ok"] is False
    assert "Bootstrap failed" in str(result["message"])
    # bootout (ignored) then bootstrap (fails) -> no enable/kickstart attempted.
    assert [c[1] for c in runner.calls] == ["bootout", "bootstrap"]


def test_disable_removes_plist_and_boots_out(tmp_path: Path) -> None:
    runner = FakeRunner()
    svc = _service(tmp_path, runner=runner)
    svc.enable(60)
    runner.calls.clear()

    result = svc.disable()

    assert result["ok"] is True
    assert not (tmp_path / "LaunchAgents" / f"{svc.LABEL}.plist").exists()
    assert [c[1] for c in runner.calls] == ["bootout"]


def test_status_reflects_enable_disable(tmp_path: Path) -> None:
    svc = _service(tmp_path, with_session=True)

    before = svc.status()
    assert before["supported"] is True
    assert before["enabled"] is False
    assert before["logged_in"] is True

    svc.enable(600)
    after = svc.status()
    assert after["enabled"] is True
    assert after["interval"] == 600


def test_interval_persists_and_clamps_to_minimum(tmp_path: Path) -> None:
    svc = _service(tmp_path)

    assert svc.get_interval() == DEFAULT_NOTIFY_INTERVAL  # no file yet
    result = svc.set_interval(5)  # below MIN -> clamped
    assert result["ok"] is True
    assert result["interval"] == MIN_NOTIFY_INTERVAL
    assert svc.get_interval() == MIN_NOTIFY_INTERVAL


def test_set_interval_reinstalls_when_enabled(tmp_path: Path) -> None:
    runner = FakeRunner()
    svc = _service(tmp_path, runner=runner)
    svc.enable(60)
    runner.calls.clear()

    svc.set_interval(900)

    # A live agent re-installs so the new cadence takes effect immediately.
    assert [c[1] for c in runner.calls] == ["bootout", "bootstrap", "enable", "kickstart"]
    plist = plistlib.loads((tmp_path / "LaunchAgents" / f"{svc.LABEL}.plist").read_bytes())
    assert plist["StartInterval"] == 900


def test_unsupported_platform_is_inert(tmp_path: Path) -> None:
    runner = FakeRunner()
    svc = _service(tmp_path, runner=runner, platform_name="linux")

    assert svc.is_supported() is False
    assert svc.enable(60)["ok"] is False
    assert svc.disable()["ok"] is False
    assert runner.calls == []  # never touches launchctl off macOS
    assert svc.status()["supported"] is False


def test_missing_binary_blocks_enable(tmp_path: Path) -> None:
    runner = FakeRunner()
    svc = _service(tmp_path, runner=runner, with_binary=False)

    assert svc.binary_available() is False
    result = svc.enable(60)
    assert result["ok"] is False
    assert "treehole" in str(result["message"])
    assert runner.calls == []
