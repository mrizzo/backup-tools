#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  run.sh — full pipeline: backup then verify integrity
#
#  USAGE:
#    bash run.sh                          # full hash verify (thorough, slower)
#    bash run.sh --quick                  # trivial verify: size+mtime only (fast)
#    bash run.sh --parallel               # use parallel hashing (faster over SMB/fast network)
#    bash run.sh /Volumes/MyDrive         # override DEST_ROOT
#    bash run.sh --quick /Volumes/MyDrive
#
#  SCHEDULE (macOS):
#    Use the launchd agents in ./launchd — cron can't reach external volumes
#    without granting Full Disk Access, and launchd also reruns missed jobs on
#    wake. See launchd/README.md:
#      bash launchd/install.sh
# ─────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -f "$SCRIPT_DIR/backup.conf.local" ]; then
  echo "Error: backup.conf.local not found."
  echo "  cp $SCRIPT_DIR/backup.conf.local.example $SCRIPT_DIR/backup.conf.local"
  echo "  then edit backup.conf.local and set DEST_ROOT and SOURCES."
  exit 1
fi

source "$SCRIPT_DIR/backup.conf"
source "$SCRIPT_DIR/backup.conf.local"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

# ── Parse args ────────────────────────────────────────────────
QUICK=0
SERIAL=1
WORKERS=3
for arg in "$@"; do
  case "$arg" in
    --quick)      QUICK=1 ;;
    --parallel)   SERIAL=0 ;;
    --workers=*)  WORKERS="${arg#--workers=}" ;;
    *)            DEST_ROOT="$arg" ;;
  esac
done

# Validate DEST_ROOT is set
if [ -z "$DEST_ROOT" ]; then
  echo -e "${RED}Error: DEST_ROOT is not set.${RESET}"
  echo "Set it in backup.conf or pass it as an argument: bash run.sh /Volumes/MyDrive"
  echo ""
  echo "Available volumes:"
  ls /Volumes/ 2>/dev/null
  exit 1
fi

BACKUP_DIR="$DEST_ROOT/Backup/${BACKUP_NAME:-$(hostname -s)}"

# ── Prechecks ────────────────────────────────────────────────
echo -e "${BOLD}── Prechecks${RESET}"

if [ -n "$REMOTE_HOST" ]; then
  # SSH reachability
  if ! ssh -o ConnectTimeout=10 -o BatchMode=yes "$REMOTE_HOST" exit 2>/dev/null; then
    echo -e "  ${RED}✗ Cannot reach $REMOTE_HOST — is it online?${RESET}"
    exit 1
  fi
  echo -e "  ${GREEN}✓ $REMOTE_HOST reachable${RESET}"

  # Destination path on remote
  if ! ssh "$REMOTE_HOST" "test -d '$DEST_ROOT'" 2>/dev/null; then
    echo -e "  ${RED}✗ $REMOTE_HOST:$DEST_ROOT not found — is the drive mounted?${RESET}"
    exit 1
  fi
  echo -e "  ${GREEN}✓ $REMOTE_HOST:$DEST_ROOT accessible${RESET}"

  FREE_KB=$(ssh "$REMOTE_HOST" "df -k '$DEST_ROOT' 2>/dev/null | awk 'NR==2{print \$4}'")

  # python3 on remote (needed to run paranoid.py over SSH)
  REMOTE_PY_VER=$(ssh "$REMOTE_HOST" "python3 -c 'import sys; print(sys.version_info.minor)' 2>/dev/null")
  if [ -z "$REMOTE_PY_VER" ] || [ "$REMOTE_PY_VER" -lt 9 ]; then
    echo -e "  ${YELLOW}⚠ python3.9+ not found on $REMOTE_HOST — integrity check will be skipped${RESET}"
    REMOTE_HAS_PYTHON=0
  else
    echo -e "  ${GREEN}✓ python3 on $REMOTE_HOST${RESET}"
    REMOTE_HAS_PYTHON=1
  fi
else
  if [ ! -d "$DEST_ROOT" ]; then
    echo -e "  ${RED}✗ $DEST_ROOT not found — is the drive mounted?${RESET}"
    exit 1
  fi
  echo -e "  ${GREEN}✓ $DEST_ROOT accessible${RESET}"
  FREE_KB=$(df -k "$DEST_ROOT" 2>/dev/null | awk 'NR==2{print $4}')
fi

# python3 (required for paranoid.py — needs 3.9+)
PYTHON3_BIN="$(command -v python3)"
if [ -z "$PYTHON3_BIN" ]; then
  echo -e "  ${RED}✗ python3 not found — required for integrity check${RESET}"
  exit 1
fi
PY_VERSION="$("$PYTHON3_BIN" -c 'import sys; print(sys.version_info.minor)' 2>/dev/null)"
if [ -z "$PY_VERSION" ] || [ "$PY_VERSION" -lt 9 ]; then
  echo -e "  ${RED}✗ python3.9+ required, found: $("$PYTHON3_BIN" --version 2>&1)${RESET}"
  exit 1
fi
echo -e "  ${GREEN}✓ $("$PYTHON3_BIN" --version)${RESET}"

# Free space warning (< 10 GB)
if [ -n "$FREE_KB" ]; then
  FREE_GB=$((FREE_KB / 1024 / 1024))
  if [ "$FREE_GB" -lt 10 ]; then
    echo -e "  ${YELLOW}⚠ Low disk space: ${FREE_GB} GB free on destination${RESET}"
  else
    echo -e "  ${GREEN}✓ ${FREE_GB} GB free on destination${RESET}"
  fi
fi
echo ""

# ── Step 1: Backup ────────────────────────────────────────────
bash "$SCRIPT_DIR/backup.sh" "$DEST_ROOT"
BACKUP_EXIT=$?

if [ $BACKUP_EXIT -ne 0 ]; then
  echo -e "${RED}✗ Backup failed — skipping integrity check.${RESET}"
  exit $BACKUP_EXIT
fi

# ── Step 2: Verify with paranoid.py ──────────────────────────
echo ""
SERIAL_FLAG=$( [ $SERIAL -eq 1 ] && echo "--serial" || echo "" )
if [ $QUICK -eq 1 ]; then
  echo -e "${BOLD}${CYAN}── Quick verify (size + mtime, no rehash)...${RESET}"
  PARANOID_FLAGS="$SERIAL_FLAG --yes --trivial --workers=$WORKERS"
else
  echo -e "${BOLD}${CYAN}── Full verify (SHA-256 hash of every file)...${RESET}"
  PARANOID_FLAGS="$SERIAL_FLAG --yes --workers=$WORKERS"
fi
# --yes: after a successful backup, accept the backup's own changes into the
# baseline so a clean run exits 0. Corruption is never auto-accepted (exit 2).
echo "────────────────────────────────────────"

# paranoid.py must be run from the parent of the target directory
BACKUP_PARENT="$(dirname "$BACKUP_DIR")"
BACKUP_NAME="$(basename "$BACKUP_DIR")"

# ── Sync .paranoid_ignore from config ────────────────────────
# Always overwrite so config is the single source of truth.
if [ -n "$REMOTE_HOST" ] && [ ! -d "$BACKUP_PARENT" ]; then
  printf '%s\n' "${PARANOID_EXCLUDES[@]}" | ssh "$REMOTE_HOST" "cat > '$BACKUP_DIR/.paranoid_ignore'" \
    || { echo -e "${RED}✗ Could not write .paranoid_ignore to $REMOTE_HOST${RESET}"; exit 1; }
else
  printf '%s\n' "${PARANOID_EXCLUDES[@]}" > "$BACKUP_DIR/.paranoid_ignore"
fi

if [ -n "$REMOTE_HOST" ] && [ ! -d "$BACKUP_PARENT" ]; then
  if [ "${REMOTE_HAS_PYTHON:-0}" -eq 0 ]; then
    echo -e "${YELLOW}⚠ Skipping integrity check — python3.9+ not available on $REMOTE_HOST${RESET}"
    echo "$(date): BACKUP OK (verify skipped — no python3 on remote)" >> "$HOME/.backup.log"
    exit 0
  fi
  # Remote backup with no local mount — push paranoid.py and run it over SSH
  echo -e "${BOLD}${CYAN}── Running paranoid.py on $REMOTE_HOST...${RESET}"
  REMOTE_PARANOID="/tmp/paranoid_run.py"
  scp -q "$SCRIPT_DIR/paranoid.py" "$REMOTE_HOST:$REMOTE_PARANOID" 2>/dev/null \
    || { echo -e "${RED}✗ Could not copy paranoid.py to $REMOTE_HOST${RESET}"; exit 1; }
  ssh -t "$REMOTE_HOST" "cd '$BACKUP_PARENT' && python3 '$REMOTE_PARANOID' $PARANOID_FLAGS '$BACKUP_NAME'"
  PARANOID_EXIT=$?
  ssh "$REMOTE_HOST" "rm -f '$REMOTE_PARANOID'" 2>/dev/null
else
  cd "$BACKUP_PARENT" || { echo -e "${RED}✗ Cannot cd to $BACKUP_PARENT${RESET}"; exit 1; }
  python3 "$SCRIPT_DIR/paranoid.py" $PARANOID_FLAGS "$BACKUP_NAME"
  PARANOID_EXIT=$?
fi

MODE_LABEL=$( [ $QUICK -eq 1 ] && echo "QUICK-VERIFY" || echo "FULL-VERIFY" )

# paranoid exit codes: 0 = no changes, 1 = benign changes (accepted into the
# baseline by --yes), 2 = corruption. A successful backup is "clean" for 0 or 1;
# only corruption is a failure.
case $PARANOID_EXIT in
  0)
    echo "$(date): $MODE_LABEL OK — no changes" >> "$HOME/.backup.log"
    exit 0
    ;;
  1)
    echo "$(date): $MODE_LABEL OK — backup changes accepted, baseline updated" >> "$HOME/.backup.log"
    exit 0
    ;;
  2)
    echo "$(date): $MODE_LABEL ⚠ POSSIBLE CORRUPTION — see output above (exit 2)" >> "$HOME/.backup.log"
    exit 2
    ;;
  *)
    echo "$(date): $MODE_LABEL — paranoid exited $PARANOID_EXIT" >> "$HOME/.backup.log"
    exit "$PARANOID_EXIT"
    ;;
esac
