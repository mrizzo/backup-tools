# backup-tools

Lean backup + integrity verification for macOS.

- **`backup.sh`** — rsyncs configured sources to a local drive or remote host over SSH
- **`paranoid.py`** — SHA-256 hashes every file and detects changes, corruption, moves, and duplicates
- **`run.sh`** — runs both in sequence: prechecks, backup, then verify
- **`romaji.py`** — renames CJK filenames to romaji (fixes NFD/NFC churn on non-HFS+ destinations)

## Why not just use the NAS's built-in sync?

The sync software bundled with a NAS (or any rsync/rclone job on its own) decides what to copy by comparing **metadata** — file size and modification time. That's fast, but it's blind to whole classes of problems that `paranoid.py` is built to catch:

- **🪱 Silent corruption (bitrot).** If a file's *content* changes but its size and mtime do not, vanilla sync software sees nothing to do — and will happily propagate the corrupted bytes (or leave a corrupt copy in place) without a word. `paranoid.py` re-hashes the actual content (SHA-256), so when the hash changes while the mtime hasn't, it flags the file `🪱 CORRUPT`. NAS software *cannot* catch this, because it never reads the bytes.

- **Baseline drift.** NAS sync only knows "what's on disk right now" and copies that. `paranoid.py` keeps a baseline (`__paranoid__.json`) recording what every file *was* — size, mtime, and content hash — so it can tell you exactly what drifted since the last verified-good state, instead of just mirroring the current (possibly already-degraded) snapshot.

- **Intentional-change visibility.** Applications that churn their own internals — Photos rewriting its library database, for example — show up explicitly as `✏️ UPDATED`. You see that it happened and when, rather than silently syncing a library mid-write and ending up with a potentially inconsistent snapshot on the backup.

In short: a NAS sync answers "are the two sides the same?" by trusting metadata. `paranoid.py` answers "is the data still what it was, byte for byte?" — which is the question that actually matters for an archive.

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

**Why daily quick + weekly full?** The full hash reads every byte off the backup drive, so it's too expensive to run nightly on a large archive. But bitrot is slow and rare — a detection latency of up to a week is negligible next to how long silent corruption typically sits undisturbed. The cheap daily `--quick` pass still catches everything that changes size or mtime (new files, deletes, moves, ordinary edits); the weekly deep pass exists solely to catch the same-size/same-mtime content change that metadata can't see. As long as you keep the source (or versioned `Deleted/` copies) around, the week-long window is harmless: you detect the corruption, then restore from the good side.

No PATH setup needed in crontab — `backup.sh` auto-detects Homebrew rsync.

View the log:
```bash
cat ~/.backup.log
```
