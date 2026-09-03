"""Require every CodeQL analysis lane to succeed on the exact SHA.

Branch protection names this check ``CodeQL``. GitHub Actions must publish that
job name on push to main; the GitHub Code Scanning app does not emit it for
advanced setup. This aggregator is the required context, not a substitute
label on a different job.
"""

from __future__ import annotations

import os
import sys


def verify(values: dict[str, str]) -> tuple[bool, str]:
    expected = values.get("EXPECTED_SHA", "")
    if not expected:
        return False, "missing EXPECTED_SHA"
    scripted = values.get("SCRIPTED_RESULT", "")
    android = values.get("ANDROID_RESULT", "")
    if scripted != "success":
        return False, f"scripted CodeQL analysis did not succeed: {scripted or 'missing'}"
    if android != "success":
        return False, f"Android CodeQL aggregator did not succeed: {android or 'missing'}"
    return True, f"required CodeQL context green on {expected}"


def main() -> int:
    ok, message = verify(dict(os.environ))
    print(message, file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
