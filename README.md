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
   `backup.conf` is tracked in git and holds shared settings (`EXCLUDES`) that apply to all machines.

2. Make scripts executable:
   ```bash
   chmod +x backup.sh run.sh
   ```

## Usage

```bash
# Full pipeline (prechecks + backup + verify)
bash run.sh

# Quick verify — size+mtime only, no rehash (fast)
bash run.sh --quick

# Parallel hashing — faster over SSH or fast network
bash run.sh --parallel

# Override destination at runtime
bash run.sh /Volumes/MyOtherDrive

# Backup only
bash backup.sh

# Verify only (run from parent of backup dir)
cd /Volumes/Backup/Backup
python3 /path/to/paranoid.py magatsukami

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

## SSH remote backup

Set `REMOTE_HOST` in `backup.conf` to rsync over SSH instead of a local mount:

```bash
REMOTE_HOST="mrizzo@nas.local"
DEST_ROOT="/Volumes/Backup"   # path on the remote machine
```

`run.sh` will SSH-check reachability and free space before starting. `paranoid.py` still runs locally against the mounted share — or SSH in and run it directly on the remote.

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
