# mvchck — a verified move for a single regular file.
#
# A shell FUNCTION (source this file; don't execute it). Same-filesystem moves
# use an atomic hardlink+unlink (O(1), same inode, nothing to verify). Across
# filesystems it copies, verifies the bytes with cmp, and only then removes the
# original — the paranoid-about-content stance of this repo, applied to mv.
#
# Install: add to ~/.zshrc (or ~/.bashrc):
#     source ~/code/backup-tools/mvchck.sh
#
# Usage: mvchck SOURCE DEST
#   - SOURCE must be an existing regular file (not a dir, symlink, device, …).
#   - DEST may be a target path or a directory (like mv).
#   - Refuses to overwrite an existing destination.
# Exit: 0 success · 1 error (original always preserved on failure) · 2 usage.

mvchck() {
    if (( $# != 2 )); then
        echo "usage: mvchck SOURCE DEST" >&2
        return 2
    fi

    local src="$1" dst="$2"

    [[ -e "$src" ]]                || { echo "⚠️  mvchck: source does not exist: $src" >&2; return 1; }
    [[ -f "$src" && ! -L "$src" ]] || { echo "⚠️  mvchck: source is not a regular file: $src" >&2; return 1; }

    # like mv, move into a destination directory
    [[ -d "$dst" ]] && dst="${dst%/}/${src##*/}"

    # refuse to overwrite
    [[ -e "$dst" ]] && { echo "⚠️  mvchck: destination exists: $dst" >&2; return 1; }

    # Fast path: same filesystem. A hardlink is atomic, O(1), shares the exact
    # same inode/bytes (nothing to verify) and keeps all metadata. It fails
    # (EXDEV) across filesystems, which is exactly when we fall back to copy.
    if ln -- "$src" "$dst" 2>/dev/null; then
        if rm -- "$src"; then
            echo "✅ moved (same fs) $src -> $dst"
            return 0
        fi
        echo "⚠️  mvchck: linked but could not remove source — both names exist: $src, $dst" >&2
        return 1
    fi

    # Cross-filesystem: copy, verify bytes, then delete the original.
    if ! cp -p -- "$src" "$dst"; then
        rm -f -- "$dst"
        echo "⚠️  mvchck: copy failed; partial copy removed, original preserved" >&2
        return 1
    fi
    if ! cmp -s -- "$src" "$dst"; then
        rm -f -- "$dst"
        echo "⚠️  mvchck: copy does not match source; copy removed, original preserved" >&2
        return 1
    fi
    if ! rm -- "$src"; then
        echo "⚠️  mvchck: copy verified but could not remove source — both exist: $src, $dst" >&2
        return 1
    fi
    echo "✅ moved (copy+verify) $src -> $dst"
    return 0
}
