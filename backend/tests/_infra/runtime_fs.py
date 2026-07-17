"""Fail-closed cleanup for execution-owned test runtime directories."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path


def remove_owned_runtime_tree(
    path: Path,
    *,
    owned_root: Path,
    label: str,
    attempts: int = 20,
    retry_delay_seconds: float = 0.05,
) -> None:
    """Remove one direct execution-owned child and prove it is absent."""

    if attempts < 1:
        raise ValueError("Runtime cleanup attempts must be positive")
    resolved_root = owned_root.resolve(strict=False)
    resolved_path = path.resolve(strict=False)
    if resolved_path.parent != resolved_root:
        raise RuntimeError(f"{label} is outside its declared runtime root: {path}")

    last_error: OSError | None = None
    for attempt in range(attempts):
        if not os.path.lexists(path):
            return
        try:
            shutil.rmtree(path)
        except FileNotFoundError:
            return
        except OSError as exc:
            last_error = exc
        if not os.path.lexists(path):
            return
        if attempt + 1 < attempts:
            time.sleep(retry_delay_seconds)
    raise RuntimeError(f"{label} still exists after bounded cleanup: {path}") from last_error
