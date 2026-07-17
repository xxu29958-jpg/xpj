from __future__ import annotations

import os
import re
import sys

_BRANCH = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._/-]{0,253}[A-Za-z0-9])?$")


def verify_publication_ref(*, requested_ref: str, default_branch: str) -> None:
    if _BRANCH.fullmatch(default_branch) is None or ".." in default_branch:
        raise ValueError("default branch identity is invalid")
    expected_ref = f"refs/heads/{default_branch}"
    if requested_ref != expected_ref:
        raise ValueError(
            f"Android NVD publication is restricted to {expected_ref}"
        )


def main() -> int:
    verify_publication_ref(
        requested_ref=os.environ.get("REQUESTED_REF", ""),
        default_branch=os.environ.get("DEFAULT_BRANCH", ""),
    )
    print("ANDROID_NVD_PUBLICATION_REF_VERIFIED")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
