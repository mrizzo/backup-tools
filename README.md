# backup-tools

Lean backup + integrity verification for macOS.

- **`backup.sh`** — rsyncs configured sources to a local drive or remote host over SSH
- **`paranoid.py`** — SHA-256 hashes every file and detects changes, corruption, moves, and duplicates
- **`run.sh`** — runs both in sequence: prechecks, backup, then verify
- **`romaji.py`** — renames CJK filenames to romaji (fixes NFD/NFC churn on non-HFS+ destinations)

## Requirements

- **GNU rsync 3.x** — macOS ships `openrsync` which is missing required flags. `backup.sh` auto-detects Homebrew rsync at `/usr/local/bin` or `/opt/homebrew/bin`. Install:
  ```bash
  brew install rsync
  ```

- **Python 3.9+** — for `paranoid.py`. `run.sh` checks this before running.

- **SSH key auth** — required if using `REMOTE_HOST`. Set up once:
  ```bash
  ssh-keygen -t ed25519
  ssh-copy-id user@host
  ```

## Setup

1. Copy the example local config and fill it in:
   ```bash
   cp backup.conf.local.example backup.conf.local
   ```
   Then edit `backup.conf.local`:
   - Set `DEST_ROOT` to your backup drive path (local or remote)
   - Set `REMOTE_HOST="user@host"` to back up over SSH instead of a local mount — leave empty for local/SMB
   - Add or remove entries from `SOURCES`

   `backup.conf.local` is gitignored — your personal paths stay off GitHub.

2. Shared exclusion rules live in `backup.conf` (tracked in git). Edit it to add or remove patterns that apply to all machines:
   ```bash
   # example: exclude a project's build output everywhere
   'my-project/build/'
   ```

3. Make scripts executable:
   ```bash
   chmod +x backup.sh run.sh
   ```

## Config files

| File | Tracked | Purpose |
|---|---|---|
| `backup.conf` | ✅ git | Shared `EXCLUDES` — same on all machines |
| `backup.conf.local` | ❌ gitignored | Per-machine: `DEST_ROOT`, `REMOTE_HOST`, `BACKUP_NAME`, `SOURCES` |
| `backup.conf.local.example` | ✅ git | Template to copy for a new machine |

## Usage

```bash
# Full pipeline (prechecks + backup + verify)
bash run.sh

# Quick verify — size+mtime only, no rehash (fast)
bash run.sh --quick

# More parallel hash workers (faster on fast storage or NAS)
bash run.sh --workers=6

# Override destination at runtime
bash run.sh /Volumes/MyOtherDrive

# Backup only
bash backup.sh

# Verify only (run from parent of backup dir)
cd /Volumes/Backup/Backup
python3 /path/to/paranoid.py magatsukami

# Verify with more workers
python3 /path/to/paranoid.py --workers 6 magatsukami

# Rename CJK filenames to romaji (fixes NFD/NFC churn on SMB/exFAT)
python3 romaji.py ~/Downloads          # preview
python3 romaji.py ~/Downloads --apply  # rename
```

## How it works

`backup.sh` rsyncs each source in `SOURCES` to:
```
$DEST_ROOT/Backup/<BACKUP_NAME>/
```

Deleted or overwritten files are preserved in:
```
$DEST_ROOT/Deleted/<date>/
```

`run.sh` runs prechecks before starting — verifies host reachability, destination accessibility, free space, and Python version — then calls `paranoid.py --no` on the backup destination. On first run it creates a `__paranoid__.json` hash file. On subsequent runs it compares against that baseline and reports:

| Symbol | Meaning |
|---|---|
| ✨ NEW | File added since last verify |
| 🗑️ DELETED | File removed since last verify |
| 🔀 MOVED | File renamed or reorganized |
| ✏️ UPDATED | File changed (mtime changed) |
| 🪱 CORRUPT | Hash changed but mtime didn't — possible corruption |
| 👯 DUPES | Identical files (verbose mode only) |

### paranoid.py flags

| Flag | Default | Description |
|---|---|---|
| `--trivial` / `-t` | off | Size + mtime only, no SHA-256 (fast, misses silent corruption) |
| `--serial` / `-s` | off | Single worker — use for slow external drives |
| `--workers N` / `-w N` | 3 | Parallel hash workers — increase for fast local SSDs or NAS |
| `--no` / `-n` | off | Don't prompt to update the hash file |
| `--verbose` / `-v` | off | Show per-file details and duplicate listing |

## SSH remote backup

Set `REMOTE_HOST` in `backup.conf.local` to rsync over SSH instead of a local mount:

```bash
REMOTE_HOST="mrizzo@nas.local"
DEST_ROOT="/Volumes/Backup"   # path on the remote machine
```

`run.sh` checks reachability, free space, and python3 availability on the remote before starting. If the remote has Python 3.9+, `paranoid.py` is copied over SSH and run there automatically — no permanent install needed. If python3 isn't available on the remote, the integrity check is skipped with a log entry.

## Schedule

```bash
crontab -e
# Daily quick check (size + mtime, fast — misses silent corruption):
0 2 * * *   /bin/bash /path/to/run.sh --quick >> $HOME/.backup.log 2>&1
# Weekly full hash (Sunday 3am — catches silent corruption):
0 3 * * 0   /bin/bash /path/to/run.sh         >> $HOME/.backup.log 2>&1
```

No PATH setup needed in crontab — `backup.sh` auto-detects Homebrew rsync.

View the log:
```bash
cat ~/.backup.log
```
