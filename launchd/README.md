# Scheduling with launchd (macOS)

These LaunchAgents replace the old crontab entries for the nightly/weekly backup.

## Why not cron?

On macOS, **cron has no privacy (TCC) grants**, so a cron job touching an
external/removable volume (e.g. `/Volumes/...`) fails with **`Operation not
permitted`** (EPERM) — even though the same command works in an interactive
Terminal. `launchd` is Apple's supported scheduler and, unlike cron, also runs a
**missed occurrence once on wake** if the Mac was asleep at the scheduled time.

Either way you must grant Full Disk Access (see below) — but launchd is the
cleaner long-term home.

## What gets installed

| Agent | Schedule | Command |
|-------|----------|---------|
| `local.backup-tools.quick` | daily 02:00 | `run.sh --quick` (size + mtime verify) |
| `local.backup-tools.full`  | Sunday 03:00 | `run.sh` (full SHA-256 verify) |

Output goes to `~/.backup.log` (same as before).

## Install

```bash
bash launchd/install.sh
```

This substitutes the absolute paths into the plists, loads the agents into your
GUI session, and removes the old cron entries (backing the crontab up to
`~/.backup-tools-crontab.backup.*.txt` first).

## Required: grant Full Disk Access

The agents run `/bin/bash run.sh`, so grant FDA to **`/bin/bash`**:

1. System Settings → Privacy & Security → Full Disk Access
2. **+**, then ⌘⇧G, enter `/bin/bash`, add it, toggle **ON**

Without this you'll keep seeing `Operation not permitted` on the external volume.

## Verify / operate

```bash
launchctl list | grep backup-tools                              # is it loaded?
launchctl kickstart -k gui/$(id -u)/local.backup-tools.quick    # run now
tail -f ~/.backup.log                                           # watch output
```

## Uninstall

```bash
bash launchd/uninstall.sh
```
