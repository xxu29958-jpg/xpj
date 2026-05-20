"""Test infrastructure (fixtures, lifecycle, env wiring).

Public test API lives in ``tests/conftest.py``. This package holds the
implementation split by concern:

- ``env``      — TEST_* path/token constants + os.environ wiring (must import
                 first, before any ``app.*`` import, so app.config reads the
                 right env)
- ``identity`` — TestIdentity dataclass + seed_identity() factory that bootstraps
                 owner + per-tenant devices/tokens and returns the resulting
                 secrets to the caller (no module-level globals here — the
                 caller decides whether to expose them)
- ``db``       — schema lifecycle helpers (reset_runtime, cleanup_runtime)
- ``client``   — TestClient fixture + dependency overrides
"""
