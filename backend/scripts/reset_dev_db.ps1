# reset_dev_db.ps1 -- DEV ONLY
# Reset the development PostgreSQL database: drop all app tables, then re-init
# (create_all + Alembic stamp + seed). Local development only; never run on real
# data. Refuses to run unless DATABASE_URL points at a loopback host.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = @'
from urllib.parse import urlparse
from app.config import get_settings
from app.database import Base, engine, init_db
host = (urlparse(get_settings().database_url).hostname or "").lower()
if host not in {"localhost", "127.0.0.1", "::1", ""}:
    raise SystemExit(f"refusing reset: DATABASE_URL host {host!r} is not loopback (dev-only script)")
Base.metadata.drop_all(bind=engine)
init_db()
print("reset OK")
'@
Push-Location $root
try {
    & .\.venv\Scripts\python.exe -c $py
} finally {
    Pop-Location
}