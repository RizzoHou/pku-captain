#!/bin/bash
# Remove the Treehole notification LaunchAgent.
set -euo pipefail
LABEL="com.pku.treehole.notify"
UID_NUM="$(id -u)"
launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
echo "removed $LABEL (watchlist, state, and logs left in place)"
