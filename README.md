# backup-tools

Lean backup + integrity verification for macOS.

- **`backup.sh`** — rsyncs configured sources to an external drive
- **`paranoid.py`** — SHA-256 hashes every file and detects changes, corruption, moves, and duplicates
- **`run.sh`** — runs both in sequence: backup first, then verify

## Requirements

**GNU rsync 3.x** is required. macOS ships `openrsync` (Apple's BSD reimplementation) which is missing flags this script depends on. Install the real thing:

```bash
brew install rsync
```

Confirm you have the right one:
```bash
rsync --version  # should say "rsync  version 3.x" not "openrsync"
```

If `brew install rsync` doesn't take precedence, add `/opt/homebrew/bin` (Apple Silicon) or `/usr/local/bin` (Intel) to the front of your `$PATH` in `~/.zshrc`.

## Setup

1. Edit `backup.conf`:
   - Set `DEST_ROOT` to your backup drive mount point (e.g. `/Volumes/SanDisk`)
   - Add or remove entries from `SOURCES`

2. Make scripts executable:
   ```bash
   chmod +x backup.sh run.sh paranoid.py
   ```

## Usage

```bash
# Full pipeline (backup + verify)
bash run.sh

# Override destination at runtime
bash run.sh /Volumes/MyOtherDrive

# Backup only
bash backup.sh

# Verify only (run from parent of backup dir)
cd /Volumes/SanDisk/Backup
python3 /path/to/paranoid.py <hostname>
```

## How it works

`backup.sh` rsyncs each source in `SOURCES` to:
```
$DEST_ROOT/Backup/<hostname>/
```

Deleted files are preserved (not lost) in:
```
$DEST_ROOT/Deleted/<date>/
```

After backup, `run.sh` calls `paranoid.py --serial --no` on the backup destination. On first run it creates a `__paranoid__.json` hash file. On subsequent runs it compares against that baseline and reports:

| Symbol | Meaning |
|---|---|
| ✨ NEW | File added since last verify |
| 🗑️ DELETED | File removed since last verify |
| 🔀 MOVED | File renamed or reorganized |
| ✏️ UPDATED | File changed (mtime changed) |
| 🪱 CORRUPT | Hash changed but mtime didn't — possible corruption |
| 👯 DUPES | Identical files (verbose mode only) |

## Schedule

To run daily at 9am via cron:
```bash
crontab -e
# Add:
0 9 * * * /bin/bash /path/to/run.sh >> $HOME/.backup.log 2>&1
```

View the log:
```bash
cat ~/.backup.log
```
