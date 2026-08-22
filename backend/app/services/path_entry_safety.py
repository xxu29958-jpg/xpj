"""No-follow classification for filesystem entries used by maintenance owners."""

from __future__ import annotations

import os
import stat
from pathlib import Path

_WINDOWS_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def is_link_or_reparse(path: Path) -> bool:
    """Return whether the exact directory entry redirects filesystem access."""

    if path.is_symlink():
        return True
    try:
        entry = os.lstat(path)
    except FileNotFoundError:
        return False
    return bool(getattr(entry, "st_file_attributes", 0) & _WINDOWS_REPARSE_POINT)


__all__ = ["is_link_or_reparse"]
