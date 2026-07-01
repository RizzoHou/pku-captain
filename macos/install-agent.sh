#!/bin/bash
# Install a per-user LaunchAgent that polls Treehole and posts macOS notifications
# for new replies on your watched holes. Single-shot per tick (StartInterval), so a
# session that needs SMS re-verification does not restart-storm.
#
#   macos/install-agent.sh [--interval SECONDS] [--holes pid1,pid2,...]
#
#   --interval  poll period in seconds (default 60; set anything you like)
#   --holes     comma-separated pids to watch; written to secrets/watchlist.
#               Omit to (re)use an existing secrets/watchlist, or to watch ALL
#               followed holes if no watchlist exists.
#
# Re-run any time to change the interval or watchlist; it reloads in place.
set -euo pipefail

LABEL="com.pku.treehole.notify"
INTERVAL=60
HOLES=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --interval) INTERVAL="$2"; shift 2 ;;
    --holes)    HOLES="$2";    shift 2 ;;
    -h|--help)  grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

REPO="$(cd "$(dirname "$0")/.." && pwd)"
TREEHOLE="$REPO/.venv/bin/treehole"
[[ -x "$TREEHOLE" ]] || { echo "missing venv entrypoint: $TREEHOLE
run: python3 -m venv .venv && .venv/bin/pip install -e . first" >&2; exit 1; }

WATCHLIST="$REPO/secrets/watchlist"
if [[ -n "$HOLES" ]]; then
  mkdir -p "$REPO/secrets"
  printf '%s\n' ${HOLES//,/ } > "$WATCHLIST"
  echo "wrote watchlist ($(grep -c . "$WATCHLIST") holes) -> $WATCHLIST"
fi

STATE="$REPO/secrets/notify-state.json"
LOGDIR="$REPO/logs"; mkdir -p "$LOGDIR"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
UID_NUM="$(id -u)"

HOLES_ARG=""
if [[ -f "$WATCHLIST" ]]; then
  HOLES_ARG="    <string>--holes-file</string><string>$WATCHLIST</string>"
  echo "watching $(grep -c . "$WATCHLIST") hole(s) from $WATCHLIST"
else
  echo "no watchlist -> watching ALL followed holes"
fi

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$TREEHOLE</string>
    <string>--secrets-dir</string><string>$REPO/secrets</string>
    <string>monitor</string>
    <string>--state</string><string>$STATE</string>
$HOLES_ARG
    <string>--notify</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>StartInterval</key><integer>$INTERVAL</integer>
  <key>RunAtLoad</key><true/>
  <key>ProcessType</key><string>Background</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
  <key>StandardOutPath</key><string>$LOGDIR/notify.out.log</string>
  <key>StandardErrorPath</key><string>$LOGDIR/notify.err.log</string>
</dict>
</plist>
PLIST
echo "wrote $PLIST (interval=${INTERVAL}s)"

# Reload into the GUI domain so notifications land in the Aqua session.
launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID_NUM" "$PLIST"
launchctl enable "gui/$UID_NUM/$LABEL"
launchctl kickstart "gui/$UID_NUM/$LABEL"   # run one tick now

echo
echo "loaded. first tick just ran (cold-start baselines silently; no banner expected)."
echo "  status: launchctl print gui/$UID_NUM/$LABEL | grep -E 'state|last exit'"
echo "  logs:   $LOGDIR/notify.{out,err}.log"
echo "  edit watchlist: $WATCHLIST  then  launchctl kickstart gui/$UID_NUM/$LABEL"
echo "  remove: macos/uninstall-agent.sh"
echo
echo "NOTE: the first real notification may be suppressed until you allow"
echo "notifications for \"Script Editor\" in System Settings > Notifications."
echo "(Delivery is osascript-only; do NOT install terminal-notifier -- it is dead"
echo " on macOS 26 and would silently swallow every banner.)"
