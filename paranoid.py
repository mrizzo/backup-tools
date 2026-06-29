#!/usr/bin/env python3
# SPDX-License-Identifier: MIT

import sys
if sys.version_info < (3, 9):
    sys.exit("error: Python 3.9 or newer required")

import os
import json
import time
import shutil
import platform
import hashlib
import argparse
import fnmatch
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pprint import pprint
from pathlib import Path
import multiprocessing

__version__ = "1.0.0"

@dataclass(frozen=True)
class HashedFile:
    st_size     : int
    st_mtime    : int
    hash_deep   : str
    hash_time   : str

def fingerprint_HF(_hf, _trivial):
    if _trivial:
        return f"{_hf.st_size}|{_hf.st_mtime}"
    else:
        return _hf.hash_deep

NEW_STR     = "✨ NEW    : "
DELETED_STR = "🗑️  DELETED: "
MOVED_STR   = "🔀 MOVED  : "
UPDATED_STR = "✏️  UPDATED: "
CORRUPT_STR = "🪱 CORRUPT: "
DUPE_STR    = "👯 DUPES  : "

def live_hash_file(_file_trivial):
    (_file, _trivial) = _file_trivial

    try:
      return _live_hash_file_inner(_file, _trivial)
    except OSError as e:
        print(f"\n  SKIP {_file}: {e}", file=sys.stderr)
        return None

def _live_hash_file_inner(_file, _trivial):
    with Path(_file).open('rb') as f:
        st1 = os.fstat(f.fileno())

        if _trivial:
            hash_deep = None
        else:
            h = hashlib.sha256()
            CHUNK_SIZE = 4 * (2**20) # 4 MiB
            while data := f.read(CHUNK_SIZE):
                h.update(data)

            hash_deep = f"sha256:{h.hexdigest()}"


        # re-stat to detect concurrent modification
        if (
            (st2 := os.fstat(f.fileno())).st_mtime != st1.st_mtime
            or st2.st_size != st1.st_size
        ): raise RuntimeError(f"file modified during hashing: {_file}")

        return (
            _file,
            HashedFile(
                st1.st_size,
                int(st1.st_mtime),
                hash_deep,
                datetime.now(timezone.utc)
                    .isoformat(timespec='seconds') # don't use microseconds
                    .replace('+00:00', 'Z') # use Z shorthand for UTC timezone
            )
        )

def live_hash_files(_files, _trivial, _serial, _workers=3):
    total_file_size = 0
    start_wall_time = time.perf_counter()

    CLEAR_STATUS_LINE = "\r\033[2K" # \r -> go to column 0, \033[2K -> clear the whole line
    STATUS_MAX_WIDTH = max(0, shutil.get_terminal_size(fallback=(120, 20)).columns - 2)

    # get the hashes and file size of every file
    hashes_live = {}
    with multiprocessing.Pool(processes=1 if _serial else _workers) as pool:
        try:
            pool_tasks = [(f, _trivial) for f in _files]

            jobs_total = len(pool_tasks)
            jobs_done  = 0

            BAR_PENDING_CHAR = '░'
            BAR_DONE_CHAR    = '▓'
            BAR_NUM          = 20

            # uncoupling the iterator instantiation from the loop forces worker failures to trigger inside the try block, preventing unhandled hangs
            result_iterator = pool.imap_unordered(live_hash_file, pool_tasks, chunksize=1)
            for result in result_iterator:
                if result is None:
                    jobs_total -= 1  # keep progress bar accurate
                    continue
                (hf_name, hf) = result
                jobs_done += 1

                # print status every 10 files — flush=True per-file is a syscall
                # bottleneck when workers are returning results faster than the
                # terminal can consume them
                if jobs_done % 10 == 0 or jobs_done == jobs_total:
                    decile_done = int(BAR_NUM * jobs_done / jobs_total)
                    progress_bar = f"[{BAR_DONE_CHAR * decile_done}{BAR_PENDING_CHAR * (BAR_NUM - decile_done)}]"

                    status = f"{progress_bar} ({jobs_done}/{jobs_total})"
                    status = status[:STATUS_MAX_WIDTH]
                    print(f"{CLEAR_STATUS_LINE}{status}", end="", flush=True)

                hashes_live[hf_name] = hf # HashedFile

                total_file_size += hf.st_size
        except KeyboardInterrupt:
            print("\nInterrupted — terminating workers...", file=sys.stderr)
            pool.terminate()
            pool.join()
            raise
        except Exception as e:
            print(f"{CLEAR_STATUS_LINE}\nWorker failed: {e}", file=sys.stderr) # newline to clear the live progress bar line
            pool.terminate()
            pool.join()
            raise

    # clear out last printed line
    print(CLEAR_STATUS_LINE, end='', flush=True)
    elapsed_hash = time.perf_counter() - start_wall_time
    if hashes_live:
        if _trivial:
            print(f"Scanned  {len(hashes_live):,} files in {elapsed_hash:.1f}s")
        else:
            print(f"Hashed   {len(hashes_live):,} files ({total_file_size/2**30:.1f} GiB) in {elapsed_hash:.1f}s @ {(total_file_size/elapsed_hash)/2**20:,.1f} MiB/s")

    return hashes_live

''' ---------------------------------------------------- '''

IGNOREFILE_NAME = '.paranoid_ignore'
HASHFILE_NAME   = '__paranoid__.json'

_SPECIAL_FILES = frozenset({HASHFILE_NAME})
_SPECIAL_DIRS  = frozenset()
if platform.system() == 'Darwin':
    _SPECIAL_FILES |= frozenset({'.DS_Store', 'Thumbs.db', '.localized'})
    _SPECIAL_DIRS  |= frozenset({'.fseventsd', '.Spotlight-V100', '.TemporaryItems', '.Trashes'})

def hashfile_path(_searchpath):
    return _searchpath / HASHFILE_NAME

SUPERHASH_KEY = '\x00superhash\x00' # null bytes are illegal in all filesystem paths — guaranteed no collision

def _compute_superhash(_hashed_files: dict[str, HashedFile]) -> str:
    h = hashlib.sha256()
    for k in sorted(_hashed_files):
        hf = _hashed_files[k]
        h.update(f"{k}\x00{hf.st_size}\x00{hf.st_mtime}\x00{hf.hash_deep}\x00{hf.hash_time}\x00".encode())
    return h.hexdigest()

def save_hashdict(_searchpath, _hashed_files: dict[str, HashedFile]):
    if any(hf.hash_deep is None for hf in _hashed_files.values()):
        raise RuntimeError("attempted to save hash dict with empty deep hashes") # we never save empty deep hashes

    dict_j = {k: asdict(v) for k, v in _hashed_files.items()} # create dict from HashedFile's
    dict_j[SUPERHASH_KEY] = _compute_superhash(_hashed_files)

    hf_path  = hashfile_path(_searchpath)
    tmp_path = hf_path.with_suffix('.tmp')

    with tmp_path.open('w') as f:
        json.dump(
            dict_j,
            f,
            indent=4,
            sort_keys=True,
            ensure_ascii=False # sort lexographically for diffs, allow unicode characters
        )
        f.write('\n') # trailing newline
        # ensure file is written prior to replace()
        f.flush()
        os.fsync(f.fileno())
    tmp_path.replace(hf_path) # atomic

    # fsync parent directory to persist the new directory entry
    dir_fd = os.open(str(hf_path.parent), os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)

    print(f"Saved {hf_path}")

def load_hashdict(_searchpath):
    hf_path = hashfile_path(_searchpath)
    if not hf_path.is_file():
        return None

    with hf_path.open('r') as f:
        try:
            j = json.load(f)
        except (TypeError, json.JSONDecodeError):
            if (input(f"WARNING: '{hf_path}' is corrupt and will be overwritten. Proceed? (y): ") != 'y'):
                raise SystemExit("aborting")
            return None

    saved_superhash = j.pop(SUPERHASH_KEY, None)
    hashed_files = {k: HashedFile(**v) for k, v in j.items()}

    if saved_superhash is not None:
        computed = _compute_superhash(hashed_files)
        if computed != saved_superhash:
            raise SystemExit(f"ERROR: '{hf_path}' failed integrity check — the hash database itself may be corrupt. Delete it and re-run to rebuild.")

    return hashed_files

def ignore_file(_f_test, _dir_ignore_patterns, _args):
    if _f_test.name in _SPECIAL_FILES:
        return True

    for p in _f_test.parents:
        if p.name in _SPECIAL_DIRS:
            return True

    for _f_test_ancestor in _f_test.parents:
        patterns = _dir_ignore_patterns.get(_f_test_ancestor)
        if not patterns:
            continue

        rel = _f_test.relative_to(_f_test_ancestor)
        for i_p in patterns:
            if i_p.endswith('/'): # directory pattern
                i_ps = i_p.rstrip('/')
                if '/' in i_ps:
                    # multi-component directory name pattern: match against path prefixes
                    for depth in range(1, len(rel.parts)):
                        rel_prefix = '/'.join(rel.parts[:depth])
                        if fnmatch.fnmatch(rel_prefix, i_ps):
                            if _args.verbose:
                                print(f"Ignoring '{str(_f_test)}' (directory pattern '{i_p}' from {_f_test_ancestor / IGNOREFILE_NAME})")
                            return True
                else:
                    # simple directory name pattern: match against individual components
                    for f_dir_part in rel.parts[:-1]:
                        if fnmatch.fnmatch(f_dir_part, i_ps):
                            if _args.verbose:
                                print(f"Ignoring '{str(_f_test)}' (directory pattern '{i_p}' from {_f_test_ancestor / IGNOREFILE_NAME})")
                            return True
            elif '/' in i_p: # relative file name pattern (pattern contains '/' but doesn't end with '/'): match against path relative to ignore file's directory
                if fnmatch.fnmatch('/'.join(rel.parts), i_p):
                    if _args.verbose:
                        print(f"Ignoring '{str(_f_test)}' (relative pattern '{i_p}' from {_f_test_ancestor / IGNOREFILE_NAME})")
                    return True
            else:
                # file name pattern
                if fnmatch.fnmatch(_f_test.name, i_p):
                    if _args.verbose:
                        print(f"Ignoring '{str(_f_test)}' (file pattern '{i_p}' from {_f_test_ancestor / IGNOREFILE_NAME})")
                    return True

    return False

def list_files(_searchpath, _args):
    files = []
    dir_ignore_patterns = {}

    # pathlib.Path.rglob() does not follow symlinks for recursive directory traversal.
    # this behavior was implemented to prevent issues like infinite loops when dealing with circular symlinks.
    print(f"Listing files in {_searchpath}...")
    for f in _searchpath.rglob('*'):
        if f.is_symlink() or not f.is_file():
            pass
        elif f.name == IGNOREFILE_NAME:
            if _args.verbose:
                print("Loading ignore file " + str(f))

            with f.open('r') as i:
                for line_p in i:
                    line_p = line_p.strip()
                    if line_p and not line_p.startswith('#'): # if not an empty line or a comment
                        dir_ignore_patterns.setdefault(
                            f.parent, # the ignorefile's directory location
                            []        # the ignorefile's list of patterns
                        ).append(line_p)
        else:
            files.append(f)

    # filter ignored files by matching directories with ignore patterns
    if dir_ignore_patterns:
        print(f"Processing ignore files...")

    # Path.as_posix() returns deterministic path across OSes, always gives forward slashes, unlike str(Path)
    return [f.as_posix() for f in sorted(files) if not ignore_file(f, dir_ignore_patterns, _args)]

def ago_from_iso8601(_ts):
    _ts = datetime.fromisoformat(_ts)
    now = datetime.now(timezone.utc)

    seconds = int((now - _ts).total_seconds())

    days    = seconds // 86400
    hours   = seconds // 3600
    minutes = seconds // 60

    if (value := days // 365):
        unit = "year"
    elif (value := days // 31):
        unit = "month"
    elif (value := days // 7):
        unit = "week"
    elif (value := days):
        unit = "day"
    elif (value := hours):
        unit = "hour"
    elif (value := minutes):
        unit = "minute"
    else:
        value = seconds
        unit = "second"

    return f"{value} {unit}{'s' if value != 1 else ''} ago"

def work(_searchpath, _args):
    hashes_saved = load_hashdict(_searchpath)
    if hashes_saved is None:
        if _args.trivial:
            raise SystemExit(f"error: --trivial requires existing dictionary at {hashfile_path(_searchpath)}; run without --trivial first")

    # get all files in searchpath
    files_live = list_files(_searchpath, _args)

    # live hashes
    hashes_live = live_hash_files(files_live, _args.trivial, _args.serial, _args.workers) # keys are Path.as_posix()

    if hashes_saved is None:
        # hashfile does not exist, create the dict
        save_hashdict(_searchpath, hashes_live)
        return 0 # no changes

    verify_start = time.perf_counter()

    fileset_updated = set()
    fileset_corrupt = set()
    for f in set(hashes_live) & set(hashes_saved):
        # live hash doesn't match saved hash
        if fingerprint_HF(hashes_saved[f], _args.trivial) != fingerprint_HF(hashes_live[f], _args.trivial):
            # if hash changed, but timestamp is still the same, this could indicate corruption
            if hashes_saved[f].st_mtime == hashes_live[f].st_mtime:
                fileset_corrupt.add(f)
                # simulate a corrupt file by changing contents and restoring original mtime:
                # 1. stat -f "%m" <file>
                # 2. edit <file>
                # 3. touch -t $(date -r <original_mtime> +%Y%m%d%H%M.%S) <file>
            else:
                fileset_updated.add(f)

    fileset_new     = hashes_live.keys() - hashes_saved.keys()
    fileset_deleted = hashes_saved.keys() - hashes_live.keys()

    files_mis_by_hash = {}
    for f_mis in fileset_deleted:
        files_mis_by_hash.setdefault(fingerprint_HF(hashes_saved[f_mis], _args.trivial), []).append(f_mis)

    files_new_by_hash = {}
    for f_new in fileset_new:
        files_new_by_hash.setdefault(fingerprint_HF(hashes_live[f_new], _args.trivial), []).append(f_new)

    # moved files are identical files that are both deleted and new
    fileset_moved  = set()
    for h in files_mis_by_hash.keys() & files_new_by_hash.keys():
        if len(files_mis_by_hash[h]) == 1 and len(files_new_by_hash[h]) == 1:
            f_mis = files_mis_by_hash[h][0]
            f_new = files_new_by_hash[h][0]

            fileset_moved.add((f_mis, f_new))
            # don't need these anymore
            fileset_deleted.remove(f_mis)
            fileset_new.remove(f_new)

    print(f"Verified {len(hashes_live):,} files in {time.perf_counter() - verify_start:.3f}s")

    OFFSET_TAB = ' '*(len(DUPE_STR)+1)

    # list file groups
    GROUP_INDENT_CHAR = '▶'
    # NEW
    for f in sorted(fileset_new):
        print(f"{NEW_STR}{f}")
    # DELETED
    for f in sorted(fileset_deleted):
        print(f"{DELETED_STR}{f}")
        if _args.verbose:
            print(f"{OFFSET_TAB}{GROUP_INDENT_CHAR} hashed {ago_from_iso8601(hashes_saved[f].hash_time)}")
    # MOVED
    for (f_mis, f_new) in sorted(fileset_moved):
        print(f"{MOVED_STR}{f_mis} -> {f_new}")
        if _args.verbose:
            print(f"{OFFSET_TAB}{GROUP_INDENT_CHAR} hashed {ago_from_iso8601(hashes_saved[f_mis].hash_time)}")
    # UPDATED
    for f in sorted(fileset_updated):
        print(f"{UPDATED_STR}{f}")
        if _args.verbose:
            print(f"{OFFSET_TAB}{GROUP_INDENT_CHAR} hashed {ago_from_iso8601(hashes_saved[f].hash_time)}")
    # CORRUPT
    for f in sorted(fileset_corrupt):
        print(f"{CORRUPT_STR}{f}")
        # always show, even if not --verbose
        print(f"{OFFSET_TAB}{GROUP_INDENT_CHAR} hashed {ago_from_iso8601(hashes_saved[f].hash_time)}")

        if _args.trivial:
            print(f"{OFFSET_TAB}{GROUP_INDENT_CHAR} size changed but mtime unchanged — possible file corruption")
        else:
            print(f"{OFFSET_TAB}{GROUP_INDENT_CHAR} hash changed but mtime unchanged — possible file corruption")

    # list dupe groups by deep hash (trivial hashes are not meaningful for dupe detection)
    # DUPES
    num_dupes = 0
    if not _args.trivial:
        live_deephashes = {}
        for (f, h) in hashes_live.items():
            # ignore empty files as dupes, these are common
            if h.st_size == 0:
                continue
            live_deephashes.setdefault(h.hash_deep, []).append(f) # use h.hash_deep since we are inside "not _args.trivial"

        for h in live_deephashes:
            h_files = live_deephashes[h]
            if len(h_files) > 1:
                num_dupes += len(h_files) - 1 # don't count the original, only dupes
                if _args.verbose: # only print listing in verbose mode
                    print(f"{DUPE_STR}{h_files[0]}") # original file
                    for f in h_files[1:]: # all dupe files
                        print(f"{OFFSET_TAB}↳ {f}")

    summary_lines = []
    if fileset_corrupt or _args.verbose:
        summary_lines.append(f"{CORRUPT_STR}{len(fileset_corrupt)}{' (*)' if _args.trivial else ''}")
    if fileset_updated or _args.verbose:
        summary_lines.append(f"{UPDATED_STR}{len(fileset_updated)}{' (*)' if _args.trivial else ''}")
    if fileset_moved or _args.verbose:
        summary_lines.append(f"{MOVED_STR}{len(fileset_moved)}")
    if fileset_new or _args.verbose:
        summary_lines.append(f"{NEW_STR}{len(fileset_new)}")
    if fileset_deleted or _args.verbose:
        summary_lines.append(f"{DELETED_STR}{len(fileset_deleted)}")
    if _args.verbose:
        summary_lines.append(f"{DUPE_STR}{'N/A (*)' if _args.trivial else num_dupes}")

    if summary_lines:
        print('')
        print('summary of changes')
        print('---')
        print("\n".join(summary_lines))
        if _args.trivial:
            print()
            print("(*) using trivial file signature (size + modification time); run without --trivial for deep hash")
        print()

    if (fileset_new or fileset_deleted or fileset_updated or fileset_corrupt or fileset_moved):
        yn = 'n' if _args.no else None
        while yn not in ['y', 'n']:
            yn = input('Update? (y/n): ')

        if yn == 'y':
            if _args.trivial:
                # hashes_live only contains trivial hashes, we need the deep hash for all new, updated, corrupt, moved files
                files_live = [
                    f for f in files_live if
                        f in fileset_new or
                        f in fileset_updated or
                        f in fileset_corrupt or
                        f in {f_new for (_f_mis, f_new) in fileset_moved} # include moved new files (moved files were removed from fileset_new)
                ]
                hashes_live = live_hash_files(files_live, False, _args.serial, _args.workers)

            # remove moved files from saved hashes
            for (f_mis, f_new) in fileset_moved:
                hashes_saved.pop(f_mis)

            # delete deleted files from saved hashes
            for k in fileset_deleted:
                hashes_saved.pop(k)

            # merge live hashes into saved hashes
            hashes_saved |= hashes_live

            # save hash file
            save_hashdict(_searchpath, hashes_saved)

        return 1 # changes
    else:
        print("✅ No tracked file changes")
        return 0 # no changes

def main():
    parser = argparse.ArgumentParser(
        description=
    f"""Tracks and detects changes to files in a directory tree.

Examples:
  paranoid.py Photos/    # first run creates the hash file
  paranoid.py Photos/    # subsequent runs detect changes
""",
        epilog=
    f"""
Files are tracked in {HASHFILE_NAME} in the top-level directory.

Certain files or directories can be ignored using {IGNOREFILE_NAME} files.
{IGNOREFILE_NAME} uses git-style '.gitignore' simple pattern matching:
    *.pyc         file pattern      - matches filename anywhere in the tree
    .git/         directory pattern - matches any directory by name (trailing /)
    build/*.log   relative pattern  - matches relative to the {IGNOREFILE_NAME} location
    # comment     ignored
""",
    formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument('paths', type=Path, help='directories to verify', nargs='+')
    parser.add_argument('-t', '--trivial', action="store_true", help="use trivial file signature (size + modification time)")
    parser.add_argument('-s', '--serial',  action="store_true", help="use serial processing (for I/O-bound external drives)")
    parser.add_argument('-w', '--workers', type=int, default=3,  help="number of parallel hash workers (default: 3)")
    parser.add_argument('-n', '--no',      action="store_true", help="do not update hash file")
    parser.add_argument('-v', '--verbose', action="store_true", help="increase verbosity")
    parser.add_argument('--version',       action='version', version=f'%(prog)s {__version__}') # (prog) = argparse's placeholder for program name
    args = parser.parse_args()

    for p in args.paths:
        try:
            rp = p.resolve()
            cwd = Path.cwd().resolve()
        except OSError as e:
            sys.exit(
                f"error: cannot access '{p}': {e.strerror or e}.\n"
                "On macOS this usually means the running process lacks Full Disk "
                "Access to the volume (common for cron/launchd jobs reaching an "
                "external drive). Grant Full Disk Access to the scheduler/interpreter "
                "in System Settings > Privacy & Security > Full Disk Access."
            )

        if not rp.is_dir():
            parser.error(f"not a directory: '{p}'")

        if rp.parent != cwd:
            parser.error(f"run this script from the parent directory of the target: '{p}'")

    ret_val = 0
    for p in args.paths:
        w_val = work(p, args)
        ret_val = ret_val or w_val # return 1 if any are 1

    return ret_val

if __name__ == '__main__':
    import signal

    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('Interrupted')
        sys.exit(128 + signal.SIGINT) # exit_code = 128 + SIGINT, standard Unix exit code convention for interrupt signals

