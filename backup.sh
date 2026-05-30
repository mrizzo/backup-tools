#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  backup.sh — rsync backup using shared config
#
#  USAGE:
#    bash backup.sh                  # uses DEST_ROOT from backup.conf
#    bash backup.sh /Volumes/MyDrive # overrides DEST_ROOT
# ─────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -f "$SCRIPT_DIR/backup.conf" ]; then
  echo "Error: backup.conf not found."
  echo "  cp $SCRIPT_DIR/backup.conf.example $SCRIPT_DIR/backup.conf"
  echo "  then edit backup.conf and set DEST_ROOT and SOURCES."
  exit 1
fi

source "$SCRIPT_DIR/backup.conf"

# ── Config ────────────────────────────────────────────────────
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

# ── rsync version check ───────────────────────────────────────
# macOS ships 'openrsync' (Apple's BSD reimplementation) which is missing
# flags we rely on (--backup-dir with absolute path, -h, --info).
# GNU rsync 3.x is required. Install via: brew install rsync
RSYNC_BIN="$(command -v rsync)"
RSYNC_VERSION_LINE="$("$RSYNC_BIN" --version 2>&1 | head -1)"

if echo "$RSYNC_VERSION_LINE" | grep -qi "openrsync"; then
  echo -e "${RED}✗ openrsync detected — this is Apple's reimplementation and is missing required flags.${RESET}"
  echo -e "  Install GNU rsync:  ${BOLD}brew install rsync${RESET}"
  echo -e "  Then ensure it's first on your PATH, or set RSYNC_BIN in backup.conf."
  exit 1
fi

RSYNC_MAJOR=$(echo "$RSYNC_VERSION_LINE" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 | cut -d. -f1)
if [ -n "$RSYNC_MAJOR" ] && [ "$RSYNC_MAJOR" -lt 3 ]; then
  echo -e "${YELLOW}⚠ rsync $RSYNC_MAJOR.x detected — version 3.0 or newer is required.${RESET}"
  echo -e "  Install GNU rsync:  ${BOLD}brew install rsync${RESET}"
  exit 1
fi

# Optional CLI arg overrides DEST_ROOT from config
if [ -n "$1" ]; then
  DEST_ROOT="$1"
fi

# Validate DEST_ROOT is set
if [ -z "$DEST_ROOT" ]; then
  echo -e "${RED}Error: DEST_ROOT is not set.${RESET}"
  echo "Set it in backup.conf or pass it as an argument: bash backup.sh /Volumes/MyDrive"
  echo ""
  echo "Available volumes:"
  ls /Volumes/ 2>/dev/null
  exit 1
fi

# Check destination is accessible
if [ ! -d "$DEST_ROOT" ]; then
  echo -e "${RED}✗ Destination '$DEST_ROOT' is not accessible. Is the drive mounted?${RESET}"
  exit 1
fi

DEST="$DEST_ROOT/Backup/$(hostname -s)"
LOG="$HOME/.backup.log"

mkdir -p "$DEST"

echo ""
echo -e "${BOLD}${CYAN}Starting backup → $DEST${RESET}"
echo -e "${CYAN}$(date)${RESET}"
echo "────────────────────────────────────────"

START=$(date +%s)

# ── Run rsync for each source ─────────────────────────────────
for SOURCE in "${SOURCES[@]}"; do
  if [ -e "$SOURCE" ]; then
    echo -e "\n${BOLD}Backing up:${RESET} $SOURCE"
    rsync -ah --progress --delete \
      --backup \
      --backup-dir="$DEST_ROOT/Deleted/$(date +%Y-%m-%d)" \
      --exclude='.DS_Store' \
      --exclude='*.tmp' \
      --exclude='node_modules/' \
      --exclude='*.pyc' \
      --exclude='.Trash/' \
      "$SOURCE" "$DEST/"
  else
    echo -e "${RED}  Skipping $SOURCE (not found)${RESET}"
  fi
done

# ── Done ──────────────────────────────────────────────────────
END=$(date +%s)
ELAPSED=$((END - START))
MINUTES=$((ELAPSED / 60))
SECONDS_REM=$((ELAPSED % 60))

echo ""
echo "────────────────────────────────────────"
echo -e "${GREEN}${BOLD}✓ Backup complete in ${MINUTES}m ${SECONDS_REM}s${RESET}"
echo -e "  Saved to: $DEST"
echo "$(date): SUCCESS (${MINUTES}m ${SECONDS_REM}s)" >> "$LOG"

du -sh "$DEST" 2>/dev/null | awk '{print "  Total size: "$1}'
echo ""
