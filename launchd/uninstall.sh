#!/bin/bash
# Remove the backup LaunchAgents. Does not restore cron — see the
# ~/.backup-tools-crontab.backup.*.txt that install.sh saved if you need it.
set -euo pipefail

AGENTS_DIR="$HOME/Library/LaunchAgents"
UID_NUM="$(id -u)"

for label in local.backup-tools.quick local.backup-tools.full; do
  launchctl bootout "gui/$UID_NUM/$label" 2>/dev/null || true
  rm -f "$AGENTS_DIR/$label.plist"
  echo "✓ removed: $label"
done

echo "Done. Cron was not restored automatically; see ~/.backup-tools-crontab.backup.*.txt."
