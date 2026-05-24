"""v1.1 Batch 3: CSRF dual-mode test sediment audit.

The CSRF middleware (`app.middleware.csrf`) protects /web and /owner
mutating routes in two distinct modes:

* **Loopback / Owner Console** — same-origin via 127.0.0.1; the cookie
  + form-field handshake works against a real browser.
* **Public host via Cloudflare Tunnel** — same-origin via the public
  hostname (api.zen70.cn); the cookie is HTTPS-only there.

Both modes need explicit coverage, otherwise a regression that only
breaks the public-host path (e.g. cookie ``secure=`` flag flipped to
the wrong value) ships green.

This audit doesn't try to verify the *shape* of those tests — it
makes sure the canonical test files still exist and reference the
right behaviors. If you delete or rename one of these files, the
audit fails so the alarm bells go off before the test gap ships.

Exit code 0 when every required marker appears. Exit code 1 with the
missing markers listed otherwise.
"""

from __future__ import annotations

import pathlib
import sys

# Files that must exist + the substring proving the relevant assertion
# still lives there. The substring is short on purpose — it's a tripwire,
# not a test re-implementation.
REQUIRED_MARKERS: dict[str, tuple[str, ...]] = {
    "tests/test_public_web_security_layers.py": (
        # Public-host (Cloudflare Tunnel) CSRF rejection path
        "invalid_request",
        "/web/",
    ),
    "tests/test_public_host_surface_regression.py": (
        # Public host surfaces tested under a routable Cloudflare-style
        # hostname; the PUBLIC_HOST constant is the test fixture.
        "PUBLIC_HOST",
    ),
    "tests/test_web_public_host_session.py": (
        # /web public-host dual mode: cookie session redirects + cookie
        # is gated by SESSION_COOKIE_NAME from the route module.
        "SESSION_COOKIE_NAME",
        "/web/auth/login",
    ),
    "tests/test_web_app_remote_guards.py": (
        # /web routes from a non-loopback peer must 403.
        "403",
        "/web/",
    ),
}


def main() -> int:
    tests_root = pathlib.Path("tests")
    if not tests_root.is_dir():
        print(
            "audit: tests/ directory not found — run from backend/",
            file=sys.stderr,
        )
        return 1

    missing: list[str] = []
    for relative, markers in REQUIRED_MARKERS.items():
        path = pathlib.Path(relative)
        if not path.is_file():
            missing.append(f"file missing: {relative}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            missing.append(f"file unreadable: {relative}")
            continue
        for marker in markers:
            if marker not in text:
                missing.append(f"missing marker in {relative!s}: {marker!r}")

    if missing:
        print("FAIL: CSRF dual-mode coverage tripwires missing:")
        for line in missing:
            print(f"  - {line}")
        print(
            "\nThe CSRF dual-mode coverage contract requires both loopback "
            "and public-host tests. Restore the listed files / markers, or "
            "update REQUIRED_MARKERS in this audit if the test was "
            "intentionally renamed."
        )
        return 1

    print("OK: CSRF dual-mode test sediment intact.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
