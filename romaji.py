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

def is_cjk_or_kana(char):
    name = unicodedata.name(char, '')
    return any(x in name for x in ('CJK', 'HIRAGANA', 'KATAKANA'))

def romajify(name):
    p = Path(name)
    # NFC before pykakasi so ﾊﾞ (NFD katakana) → バ → 'ba', not 'ha゙'
    stem = unicodedata.normalize('NFC', p.stem)
    result = kks.convert(stem)
    parts = []
    for item in result:
        orig = item['orig']
        # only substitute CJK/kana — pass ASCII and other Unicode through as-is
        if any(is_cjk_or_kana(c) for c in orig):
            parts.append(item['hepburn'])
        else:
            parts.append(orig)
    stem_out = ''.join(parts)
    stem_out = re.sub(r'[<>:"/\\|?*]', '', stem_out)
    stem_out = re.sub(r'\s+', ' ', stem_out).strip()
    return stem_out + p.suffix

dry = '--apply' not in sys.argv
args = [a for a in sys.argv[1:] if not a.startswith('--')]
root = Path(args[0]) if args else Path('.')

# deepest paths first so child renames don't break parent paths
paths = sorted(
    (p for p in root.rglob('*') if any(is_cjk_or_kana(c) for c in p.name)),
    key=lambda p: len(p.parts),
    reverse=True,
)

if not paths:
    print("No non-ASCII filenames found.")
    sys.exit(0)

for path in paths:
    new_name = romajify(path.name)
    if new_name == path.name:
        continue
    new_path = path.parent / new_name
    if new_path.exists():
        print(f"  SKIP    {path.name!r}  →  {new_name!r}  (collision)")
        continue
    print(f"  {'DRY   ' if dry else 'RENAME'}  {path.name!r}  →  {new_name!r}")
    if not dry:
        path.rename(new_path)

if dry and paths:
    print("\nDry run — pass --apply to rename.")
