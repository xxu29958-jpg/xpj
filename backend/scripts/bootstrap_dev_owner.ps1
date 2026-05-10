# bootstrap_dev_owner.ps1 -- DEV ONLY
# Initialize owner on a fresh dev DB and print admin token / upload key / pairing code.
# Local development only; never run on real data.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    & .\.venv\Scripts\python.exe -c "from app.database import init_db, SessionLocal; from app.services.identity_service import bootstrap_owner, active_auth_token_count; init_db(); db = SessionLocal();
print('ALREADY' if active_auth_token_count(db) > 0 else 'NEW');
r = None if active_auth_token_count(db) > 0 else bootstrap_owner(db);
print('admin_token=' + r.admin_token) if r else None;
print('upload_url_path=' + r.upload_url_path) if r else None;
print('pairing_code=' + r.pairing_code) if r else None;
db.close()"
} finally {
    Pop-Location
}