#!/bin/bash
# test.sh — integration tests for paranoid.py and romaji.py

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

GREEN='\033[0;32m'
RED='\033[0;31m'
BOLD='\033[1m'
RESET='\033[0m'

PASS=0
FAIL=0

pass() { echo -e "  ${GREEN}✓${RESET} $1"; PASS=$((PASS+1)); }
fail() { echo -e "  ${RED}✗${RESET} $1"; FAIL=$((FAIL+1)); }

WORK="$(mktemp -d)"
trap "rm -rf '$WORK'" EXIT

# python for paranoid (stdlib only) vs romaji (needs pykakasi in venv)
PY3="python3"
ROMAJI_PY="${SCRIPT_DIR}/.venv/bin/python3"
if [ ! -x "$ROMAJI_PY" ]; then
  ROMAJI_PY="$PY3"
fi

paranoid() { "$PY3"       "$SCRIPT_DIR/paranoid.py" "$@"; }
romaji()   { "$ROMAJI_PY" "$SCRIPT_DIR/romaji.py"   "$@"; }

# Helper: create a fresh isolated dir with a first-run hash baseline.
# Usage: setup_dir <name> [extra files...]
# Returns path in $SETUP_DIR
setup_dir() {
  local name="$1"; shift
  SETUP_DIR="$WORK/$name"
  mkdir -p "$SETUP_DIR/target"
  echo "baseline" > "$SETUP_DIR/target/base.txt"
  for f in "$@"; do
    echo "baseline" > "$SETUP_DIR/target/$f"
  done
  cd "$SETUP_DIR"
  paranoid --no target > /dev/null 2>&1
}

# ── paranoid.py ───────────────────────────────────────────────
echo -e "\n${BOLD}── paranoid.py${RESET}"

# first run creates hash file, exits 0
setup_dir "t_first"
cd "$SETUP_DIR" && paranoid --no target > /dev/null 2>&1
if [ $? -eq 0 ] && [ -f "$SETUP_DIR/target/__paranoid__.json" ]; then
  pass "first run creates hash file and exits 0"
else
  fail "first run creates hash file and exits 0"
fi

# no changes exits 0
setup_dir "t_nochange"
cd "$SETUP_DIR" && paranoid --no target > /dev/null 2>&1
if [ $? -eq 0 ]; then
  pass "no changes exits 0"
else
  fail "no changes exits 0"
fi

# detects updated file, exits 1
setup_dir "t_update"
cd "$SETUP_DIR"
echo "modified" > "$SETUP_DIR/target/base.txt"
# advance mtime so paranoid sees UPDATED (not CORRUPT — same hash change but mtime unchanged)
python3 -c "import os,time; p='$SETUP_DIR/target/base.txt'; os.utime(p, (time.time()+2, time.time()+2))"
out=$(paranoid --no target 2>&1)
ec=$?
if echo "$out" | grep -q "UPDATED" && [ $ec -eq 1 ]; then
  pass "detects updated file, exits 1"
else
  fail "detects updated file, exits 1"
fi

# detects new file
setup_dir "t_new"
cd "$SETUP_DIR"
echo "newfile" > "$SETUP_DIR/target/newfile.txt"
out=$(paranoid --no target 2>&1)
if echo "$out" | grep -q "NEW"; then
  pass "detects new file"
else
  fail "detects new file"
fi

# detects deleted file
setup_dir "t_delete" "extra.txt"
cd "$SETUP_DIR"
rm "$SETUP_DIR/target/extra.txt"
out=$(paranoid --no target 2>&1)
if echo "$out" | grep -q "DELETED"; then
  pass "detects deleted file"
else
  fail "detects deleted file"
fi

# detects moved file
setup_dir "t_move" "moveme.txt"
cd "$SETUP_DIR"
mv "$SETUP_DIR/target/moveme.txt" "$SETUP_DIR/target/moved.txt"
out=$(paranoid --no target 2>&1)
if echo "$out" | grep -q "MOVED"; then
  pass "detects moved file"
else
  fail "detects moved file"
fi

# detects corrupt file (hash changed, mtime unchanged)
setup_dir "t_corrupt"
cd "$SETUP_DIR"
saved_mtime=$(python3 -c "import json; d=json.load(open('target/__paranoid__.json')); print(list(d.values())[0]['st_mtime'])")
printf "corrupted" > "$SETUP_DIR/target/base.txt"
touch -t "$(date -r "$saved_mtime" +%Y%m%d%H%M.%S)" "$SETUP_DIR/target/base.txt"
out=$(paranoid --no target 2>&1)
if echo "$out" | grep -q "CORRUPT"; then
  pass "detects corrupt file (hash changed, mtime unchanged)"
else
  fail "detects corrupt file (hash changed, mtime unchanged)"
fi

# --trivial: first run exits 0, detects size change
setup_dir "t_trivial"
cd "$SETUP_DIR"
paranoid --no target > /dev/null 2>&1
if [ $? -eq 0 ]; then
  pass "--trivial: no changes exits 0"
else
  fail "--trivial: no changes exits 0"
fi
echo "hello world" > "$SETUP_DIR/target/base.txt"
# advance mtime so trivial fingerprint (size|mtime) changes on both dimensions
python3 -c "import os,time; p='$SETUP_DIR/target/base.txt'; os.utime(p, (time.time()+2, time.time()+2))"
out=$(paranoid --no --trivial target 2>&1)
if echo "$out" | grep -q "UPDATED"; then
  pass "--trivial: detects size change"
else
  fail "--trivial: detects size change"
fi

# --verbose: summary shows all categories
setup_dir "t_verbose"
cd "$SETUP_DIR"
out=$(paranoid --no --verbose target 2>&1)
if echo "$out" | grep -q "CORRUPT" && echo "$out" | grep -q "DUPES"; then
  pass "--verbose: summary shows all categories"
else
  fail "--verbose: summary shows all categories"
fi

# --serial: exits 0 on clean run
setup_dir "t_serial"
cd "$SETUP_DIR"
paranoid --no --serial target > /dev/null 2>&1
if [ $? -eq 0 ]; then
  pass "--serial: exits 0 on clean run"
else
  fail "--serial: exits 0 on clean run"
fi

# ── romaji.py ─────────────────────────────────────────────────
echo -e "\n${BOLD}── romaji.py${RESET}"

TR="$WORK/romaji"
mkdir -p "$TR"

# dry run: prints DRY, does not rename
touch "$TR/東京の夜.txt"
out=$(romaji "$TR" 2>&1)
if echo "$out" | grep -q "DRY"; then
  pass "dry run prints DRY"
else
  fail "dry run prints DRY"
fi
if [ -f "$TR/東京の夜.txt" ]; then
  pass "dry run does not rename file"
else
  fail "dry run does not rename file"
fi

# --apply: renames the file
romaji "$TR" --apply > /dev/null 2>&1
if [ ! -f "$TR/東京の夜.txt" ]; then
  pass "--apply renames CJK file"
else
  fail "--apply renames CJK file"
fi

# no CJK files: correct message, exits 0
TR2="$WORK/romaji2"
mkdir -p "$TR2"
touch "$TR2/normal_file.txt"
out=$(romaji "$TR2" 2>&1)
ec=$?
if echo "$out" | grep -q "No CJK" && [ $ec -eq 0 ]; then
  pass "no CJK files: correct message, exits 0"
else
  fail "no CJK files: correct message, exits 0"
fi

# non-CJK files are untouched by --apply
TR3="$WORK/romaji3"
mkdir -p "$TR3"
touch "$TR3/keep_me.txt" "$TR3/東京.txt"
romaji "$TR3" --apply > /dev/null 2>&1
if [ -f "$TR3/keep_me.txt" ]; then
  pass "non-CJK files untouched by --apply"
else
  fail "non-CJK files untouched by --apply"
fi

# ── Results ───────────────────────────────────────────────────
TOTAL=$((PASS + FAIL))
echo ""
echo "────────────────────────────────────────"
if [ $FAIL -eq 0 ]; then
  echo -e "${GREEN}${BOLD}All $TOTAL tests passed${RESET}"
else
  echo -e "${RED}${BOLD}$FAIL/$TOTAL tests failed${RESET}"
fi
echo ""
[ $FAIL -eq 0 ]
