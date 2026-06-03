#!/usr/bin/env python3
# Rename files with Japanese/CJK names to romaji. Dry-run by default.
#
# USAGE:
#   python3 romaji.py ~/Downloads          # preview
#   python3 romaji.py ~/Downloads --apply  # rename

import re, sys, unicodedata
from pathlib import Path

try:
    import pykakasi
except ImportError:
    sys.exit("pip install pykakasi")

kks = pykakasi.kakasi()

# chr() to pin codepoints explicitly — literal CJK chars used as range boundaries
# can sit at unexpected codepoints and accidentally sweep in Hangul or other scripts.
CJK_KANA_RE = re.compile(
    "["
    + chr(0x3040) + "-" + chr(0x30FF)   # Hiragana + Katakana
    + chr(0x31F0) + "-" + chr(0x31FF)   # Katakana Phonetic Extensions
    + chr(0x3400) + "-" + chr(0x4DBF)   # CJK Extension A
    + chr(0x4E00) + "-" + chr(0x9FFF)   # CJK Unified Ideographs
    + chr(0xF900) + "-" + chr(0xFAFF)   # CJK Compatibility Ideographs
    + "]+"
)


def _convert_run(m):
    return "".join(item["hepburn"] for item in kks.convert(m.group(0)))


def romajify(name):
    p = Path(name)
    # NFC first so NFD katakana (e.g. ba stored as ha + combining dakuten) converts correctly
    stem = unicodedata.normalize("NFC", p.stem)
    # Replace only CJK/kana runs; everything else (Korean, umlauts, emoji) is untouched
    stem_out = CJK_KANA_RE.sub(_convert_run, stem)
    stem_out = re.sub(r'[<>:"/\\|?*]', "", stem_out)
    stem_out = re.sub(r"\s+", " ", stem_out).strip()
    return stem_out + p.suffix


dry = "--apply" not in sys.argv
args = [a for a in sys.argv[1:] if not a.startswith("--")]
root = Path(args[0]) if args else Path(".")

# deepest paths first so child renames don't break parent paths
paths = sorted(
    (p for p in root.rglob("*") if CJK_KANA_RE.search(p.name)),
    key=lambda p: len(p.parts),
    reverse=True,
)

if not paths:
    print("No CJK/kana filenames found.")
    sys.exit(0)

for path in paths:
    new_name = romajify(path.name)
    if new_name == path.name:
        continue
    new_path = path.parent / new_name
    if new_path.exists():
        print(f"  SKIP    {path.name!r}  ->  {new_name!r}  (collision)")
        continue
    print(f"  {'DRY   ' if dry else 'RENAME'}  {path.name!r}  ->  {new_name!r}")
    if not dry:
        path.rename(new_path)

if dry:
    print("\nDry run -- pass --apply to rename.")
