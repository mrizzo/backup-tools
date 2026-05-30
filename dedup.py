#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
dedup.py — Replace duplicate files in a backup directory with hard links.

Reads __paranoid__.json for file hashes — run paranoid.py first to build it.
By default this is a dry run. Pass --apply to actually create hard links.

Hard links: both file paths remain visible and usable, but share one copy
of the data on disk. No data is lost. Freeing space is immediate.

USAGE:
  # Must be run from the parent directory of the backup target (same as paranoid.py)
  cd /Volumes/MyDrive/Backup

  python3 /path/to/dedup.py <hostname>            # dry run — show what would change
  python3 /path/to/dedup.py --apply <hostname>    # hard link duplicates
  python3 /path/to/dedup.py --apply -v <hostname> # verbose: show every file group
"""

import sys
if sys.version_info < (3, 9):
    sys.exit("error: Python 3.9 or newer required")

import os
import json
import argparse
from pathlib import Path

HASHFILE_NAME = '__paranoid__.json'


def load_hashdict(searchpath: Path) -> dict:
    hf_path = searchpath / HASHFILE_NAME
    if not hf_path.is_file():
        sys.exit(
            f"error: no {HASHFILE_NAME} found in '{searchpath}'.\n"
            f"Run paranoid.py on this directory first to build the hash database."
        )
    with hf_path.open('r') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            sys.exit(f"error: {hf_path} is corrupt or unreadable. Re-run paranoid.py.")


def fmt_size(n_bytes: int) -> str:
    if n_bytes >= 2**30:
        return f"{n_bytes / 2**30:.2f} GiB"
    if n_bytes >= 2**20:
        return f"{n_bytes / 2**20:.1f} MiB"
    if n_bytes >= 2**10:
        return f"{n_bytes / 2**10:.1f} KiB"
    return f"{n_bytes} B"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replace duplicate files in a backup directory with hard links.",
        epilog=(
            f"Run paranoid.py first to build {HASHFILE_NAME}.\n"
            "Must be run from the parent directory of the target (same rule as paranoid.py)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('path', type=Path, help='backup directory to dedup')
    parser.add_argument('--apply', action='store_true',
                        help='create hard links (default is dry run — shows only)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='show all duplicate groups')
    args = parser.parse_args()

    rp = args.path.resolve()

    if not rp.is_dir():
        parser.error(f"not a directory: '{args.path}'")

    if rp.parent != Path.cwd().resolve():
        parser.error(
            f"run this script from the parent directory of the target: '{args.path}'\n"
            f"  e.g.  cd {rp.parent} && python3 dedup.py {args.path.name}"
        )

    hashes = load_hashdict(rp)

    # Group files by deep hash, skip empty files and any without a deep hash
    by_hash: dict[str, list[str]] = {}
    for filepath, meta in hashes.items():
        h    = meta.get('hash_deep')
        size = meta.get('st_size', 0)
        if not h or size == 0:
            continue
        by_hash.setdefault(h, []).append(filepath)

    dupe_groups = {h: sorted(files) for h, files in by_hash.items() if len(files) > 1}

    if not dupe_groups:
        print("✅ No duplicates found.")
        return 0

    total_redundant = sum(len(files) - 1 for files in dupe_groups.values())
    total_reclaimable = sum(
        (len(files) - 1) * hashes[files[0]]['st_size']
        for files in dupe_groups.values()
    )

    print(f"Found {len(dupe_groups)} duplicate group(s), {total_redundant} redundant file(s)")
    print(f"Reclaimable: {fmt_size(total_reclaimable)}")
    if not args.apply:
        print()
        print("DRY RUN — pass --apply to create hard links")
    print()

    linked   = 0
    skipped  = 0
    errors   = 0
    bytes_saved = 0

    for _h, files in sorted(dupe_groups.items(), key=lambda kv: kv[1][0]):
        original   = files[0]   # keep first alphabetically as the canonical copy
        duplicates = files[1:]

        print(f"  {'[keep]':8} {original}")
        for dup in duplicates:
            size = hashes[dup]['st_size']
            label = '[dry-run]' if not args.apply else '[link]'
            print(f"  {label:8} {dup}  ({fmt_size(size)})")

            if args.apply:
                orig_path = Path.cwd() / original
                dup_path  = Path.cwd() / dup

                if not orig_path.is_file():
                    print(f"           ✗ original missing — skipping")
                    errors += 1
                    continue
                if not dup_path.is_file():
                    print(f"           ✗ duplicate missing — skipping")
                    errors += 1
                    continue

                # Already hard linked (same inode) — nothing to do
                if orig_path.stat().st_ino == dup_path.stat().st_ino:
                    print(f"           → already hard linked")
                    skipped += 1
                    continue

                try:
                    # Atomic: link to a temp file, then rename over the duplicate
                    tmp_path = dup_path.with_name(dup_path.name + '.dedup_tmp')
                    os.link(orig_path, tmp_path)
                    tmp_path.replace(dup_path)
                    linked += 1
                    bytes_saved += size
                    print(f"           ✔ hard linked")
                except Exception as e:
                    print(f"           ✗ error: {e}")
                    errors += 1
        print()

    # Summary
    print('─' * 40)
    if args.apply:
        print(f"Hard linked: {linked} file(s)")
        if skipped:
            print(f"Already linked: {skipped} file(s)")
        print(f"Reclaimed:   {fmt_size(bytes_saved)}")
        if errors:
            print(f"Errors:      {errors}")
    else:
        print(
            f"Run with --apply to hard link {total_redundant} file(s) "
            f"and reclaim {fmt_size(total_reclaimable)}"
        )

    return 1 if errors else 0


if __name__ == '__main__':
    import signal
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\nInterrupted')
        sys.exit(128 + signal.SIGINT)
