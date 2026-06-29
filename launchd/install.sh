#!/bin/bash
# Install the backup LaunchAgents and migrate off cron.
# Idempotent: re-running reloads the agents.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RUN_SH="$REPO_DIR/run.sh"
LOG="$HOME/.backup.log"
AGENTS_DIR="$HOME/Library/LaunchAgents"
UID_NUM="$(id -u)"
PATH_VALUE="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
LABELS=(local.backup-tools.quick local.backup-tools.full)

[ -f "$RUN_SH" ] || { echo "✗ run.sh not found at $RUN_SH"; exit 1; }
mkdir -p "$AGENTS_DIR"

for label in "${LABELS[@]}"; do
  dest="$AGENTS_DIR/$label.plist"
  sed -e "s|@RUN_SH@|$RUN_SH|g" -e "s|@LOG@|$LOG|g" -e "s|@PATH@|$PATH_VALUE|g" \
      "$SCRIPT_DIR/$label.plist" > "$dest"
  plutil -lint "$dest" >/dev/null
  launchctl bootout "gui/$UID_NUM/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$UID_NUM" "$dest"
  launchctl enable "gui/$UID_NUM/$label"
  echo "✓ installed + loaded: $label"
done

# Migrate off cron: remove the old backup entries (backed up first) so the job
# doesn't run twice.
if crontab -l 2>/dev/null | grep -qF "$RUN_SH"; then
  backup="$HOME/.backup-tools-crontab.backup.$(date +%Y%m%d-%H%M%S).txt"
  crontab -l > "$backup"
  crontab -l | grep -vF "$RUN_SH" | crontab -
  echo "✓ removed cron entries (backup: $backup)"
else
  echo "• no matching cron entries to remove"
fi

cat <<EOF

────────────────────────────────────────────────────────────
REQUIRED — grant Full Disk Access so the scheduled job can reach
external volumes (otherwise you'll get "Operation not permitted"):

  System Settings → Privacy & Security → Full Disk Access
  → [+] → press ⌘⇧G → enter /bin/bash → add it → toggle ON

The agents run '/bin/bash run.sh', so the grant on /bin/bash covers
the bash + python3 work it spawns.
────────────────────────────────────────────────────────────

Check loaded:  launchctl list | grep backup-tools
Run now:       launchctl kickstart -k gui/$UID_NUM/local.backup-tools.quick
Tail logs:     tail -f "$LOG"
Uninstall:     bash "$SCRIPT_DIR/uninstall.sh"
EOF
