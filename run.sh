#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  run.sh — full pipeline: backup then verify integrity
#
#  USAGE:
#    bash run.sh                     # uses DEST_ROOT from backup.conf
#    bash run.sh /Volumes/MyDrive    # overrides DEST_ROOT
#
#  SCHEDULE (daily at 9am):
#    crontab -e
#    0 9 * * * /bin/bash /path/to/run.sh >> $HOME/.backup.log 2>&1
# ─────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/backup.conf"

RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

# Optional CLI arg overrides DEST_ROOT from config
if [ -n "$1" ]; then
  DEST_ROOT="$1"
fi

# Validate DEST_ROOT is set
if [ -z "$DEST_ROOT" ]; then
  echo -e "${RED}Error: DEST_ROOT is not set.${RESET}"
  echo "Set it in backup.conf or pass it as an argument: bash run.sh /Volumes/MyDrive"
  echo ""
  echo "Available volumes:"
  ls /Volumes/ 2>/dev/null
  exit 1
fi

BACKUP_DIR="$DEST_ROOT/Backup/$(hostname -s)"

# ── Step 1: Backup ────────────────────────────────────────────
bash "$SCRIPT_DIR/backup.sh" "$DEST_ROOT"
BACKUP_EXIT=$?

if [ $BACKUP_EXIT -ne 0 ]; then
  echo -e "${RED}✗ Backup failed — skipping integrity check.${RESET}"
  exit $BACKUP_EXIT
fi

# ── Step 2: Verify with paranoid.py ──────────────────────────
echo ""
echo -e "${BOLD}${CYAN}── Verifying backup integrity...${RESET}"
echo "────────────────────────────────────────"

# paranoid.py must be run from the parent of the target directory
BACKUP_PARENT="$(dirname "$BACKUP_DIR")"
BACKUP_NAME="$(basename "$BACKUP_DIR")"

cd "$BACKUP_PARENT" || { echo -e "${RED}✗ Cannot cd to $BACKUP_PARENT${RESET}"; exit 1; }

# --serial: better for external drives (I/O bound, not CPU bound)
# --no: never auto-update the hash file; only report
python3 "$SCRIPT_DIR/paranoid.py" --serial --no "$BACKUP_NAME"
PARANOID_EXIT=$?

if [ $PARANOID_EXIT -eq 0 ]; then
  echo "$(date): VERIFY OK" >> "$HOME/.backup.log"
else
  echo "$(date): VERIFY — changes detected (exit $PARANOID_EXIT)" >> "$HOME/.backup.log"
fi

exit $PARANOID_EXIT
