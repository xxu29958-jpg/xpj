from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
HOST = "127.0.0.1"
UPLOAD_TOKEN = "smoke-upload-token"
APP_TOKEN = "smoke-app-token"
ADMIN_TOKEN = "smoke-admin-token"
SMOKE_BOOTSTRAP_SECRET = "smoke-bootstrap-secret"
SESSION_TOKEN = ""
BOOTSTRAP_ADMIN_TOKEN = ""
UPLOAD_PATH = ""


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC"
)


@dataclass
class ApiResult:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> dict | list:
        return json.loads(self.body.decode("utf-8"))


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


def app_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {SESSION_TOKEN}"}


def admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {BOOTSTRAP_ADMIN_TOKEN}"}


def request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
) -> ApiResult:
    request_headers = {"Connection": "close"}
    request_headers.update(headers or {})
    req = urllib.request.Request(url, data=body, method=method, headers=request_headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return ApiResult(
                status=response.status,
                headers=dict(response.headers.items()),
                body=response.read(),
            )
    except urllib.error.HTTPError as exc:
        return ApiResult(
            status=exc.code,
            headers=dict(exc.headers.items()),
            body=exc.read(),
        )


def multipart_body(filename: str, content_type: str, content: bytes) -> tuple[bytes, str]:
    boundary = f"----ticketbox-smoke-{uuid.uuid4().hex}"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode()
    body += content
    body += f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def assert_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value: bool, label: str) -> None:
    if not value:
        raise AssertionError(label)


def assert_error(result: ApiResult, status: int, code: str) -> None:
    assert_equal(result.status, status, f"{code} status")
    payload = result.json()
    assert_equal(payload.get("error"), code, f"{code} error code")
    assert_true(isinstance(payload.get("message"), str) and payload["message"], f"{code} message")


def clean_smoke_runtime() -> None:
    db_path = BACKEND_ROOT / "data" / "smoke_test.db"
    for _ in range(20):
        if not db_path.exists():
            break
        try:
            db_path.unlink()
            break
        except PermissionError:
            time.sleep(0.1)

    upload_dir = (BACKEND_ROOT / "uploads" / "smoke_test").resolve()
    upload_root = (BACKEND_ROOT / "uploads").resolve()
    for _ in range(20):
        if not upload_dir.exists():
            break
        try:
            upload_dir.relative_to(upload_root)
            shutil.rmtree(upload_dir)
            break
        except PermissionError:
            time.sleep(0.1)


def start_server(port: int) -> subprocess.Popen:
    env = os.environ.copy()
    env.update(
        {
            "UPLOAD_TOKEN": UPLOAD_TOKEN,
            "APP_TOKEN": APP_TOKEN,
            "ADMIN_TOKEN": ADMIN_TOKEN,
            # Default lane is file-backed SQLite. The ADR-0041 Postgres CI lane
            # sets SMOKE_DATABASE_URL=postgresql+psycopg://... to exercise the
            # full bootstrap → upload → OCC-token → confirm flow against a real
            # PostgreSQL, catching dialect drift the SQLite suite can't see.
            "DATABASE_URL": os.environ.get("SMOKE_DATABASE_URL", "sqlite:///data/smoke_test.db"),
            "UPLOAD_DIR": "uploads/smoke_test",
            "MAX_UPLOAD_SIZE_MB": "10",
            "DELETE_IMAGE_AFTER_CONFIRM": "false",
            "GENERATE_THUMBNAIL": "true",
            "OCR_PROVIDER": "empty",
            "ENABLE_HTTP_BOOTSTRAP": "true",
            "HTTP_BOOTSTRAP_SECRET": SMOKE_BOOTSTRAP_SECRET,
            "XPJ_EXTRA_LOOPBACK_HOSTS": f"{HOST}:{port}",
        }
    )
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            HOST,
            "--port",
            str(port),
            "--no-access-log",
        ],
        cwd=BACKEND_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def wait_for_server(base_url: str, process: subprocess.Popen) -> None:
    deadline = time.time() + 20
    while time.time() < deadline:
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout else ""
            raise RuntimeError(f"server exited early:\n{output}")
        try:
            result = request("GET", f"{base_url}/api/health")
            if result.status == 200:
                return
        except urllib.error.URLError:
            pass
        time.sleep(0.2)
    raise TimeoutError("server did not become ready")


def upload(base_url: str, filename: str, content_type: str, content: bytes) -> ApiResult:
    body, content_header = multipart_body(filename, content_type, content)
    return request(
        "POST",
        f"{base_url}{UPLOAD_PATH}",
        headers={
            "Content-Type": content_header,
        },
        body=body,
    )


def wait_for_expense_thumbnail(base_url: str, expense_id: int, label: str) -> dict:
    for _ in range(20):
        result = request(
            "GET",
            f"{base_url}/api/expenses/{expense_id}",
            headers=app_headers(),
        )
        assert_equal(result.status, 200, f"{label} snapshot status")
        payload = result.json()
        if payload.get("thumbnail_path"):
            return payload
        time.sleep(0.2)
    raise AssertionError(f"{label}: thumbnail enrichment did not finish")


def run_smoke(base_url: str) -> None:
    global BOOTSTRAP_ADMIN_TOKEN
    global SESSION_TOKEN
    global UPLOAD_PATH

    result = request("GET", f"{base_url}/api/health")
    assert_equal(result.status, 200, "health status")
    assert_equal(result.json()["status"], "ok", "health body")
    print("OK health")

    bootstrap_body = json.dumps(
        {
            "account_name": "我",
            "ledger_name": "我的小票夹",
            "device_name": "smoke-windows",
            "default_timezone": "Asia/Shanghai",
        },
        ensure_ascii=False,
    ).encode("utf-8")
    result = request(
        "POST",
        f"{base_url}/api/bootstrap/owner",
        headers={
            "Content-Type": "application/json",
            "X-Bootstrap-Secret": SMOKE_BOOTSTRAP_SECRET,
        },
        body=bootstrap_body,
    )
    assert_equal(result.status, 200, "bootstrap owner status")
    bootstrap = result.json()
    BOOTSTRAP_ADMIN_TOKEN = bootstrap["admin_token"]
    UPLOAD_PATH = bootstrap["upload_url_path"]
    assert_true(UPLOAD_PATH.startswith("/u/"), "bootstrap upload path")
    print("OK bootstrap owner")

    pair_body = json.dumps(
        {
            "pairing_code": bootstrap["pairing_code"],
            "device_name": "smoke-android",
            "platform": "android",
        },
        ensure_ascii=False,
    ).encode("utf-8")
    result = request(
        "POST",
        f"{base_url}/api/auth/pair",
        headers={"Content-Type": "application/json"},
        body=pair_body,
    )
    assert_equal(result.status, 200, "pairing status")
    paired = result.json()
    SESSION_TOKEN = paired["session_token"]
    assert_equal(paired["ledger_name"], "我的小票夹", "pairing ledger")
    print("OK android pairing")

    result = request("GET", f"{base_url}/api/auth/check", headers=app_headers())
    assert_equal(result.status, 200, "auth check status")
    assert_equal(result.json()["status"], "ok", "auth check body")
    assert_equal(result.json()["device_name"], "smoke-android", "auth check device")
    print("OK auth check")

    result = request("GET", f"{base_url}/api/auth/check", headers={"Authorization": f"Bearer {APP_TOKEN}"})
    assert_error(result, 401, "legacy_auth_removed")
    print("OK legacy app token removed")

    result = request("GET", f"{base_url}/api/upload/check", headers={"Upload-Token": UPLOAD_TOKEN})
    assert_error(result, 401, "legacy_auth_removed")
    result = request("GET", f"{base_url}/api/upload/check", headers={"Upload-Token": "bad"})
    assert_error(result, 401, "invalid_token")
    print("OK legacy upload token removed")

    result = request("POST", f"{base_url}/api/maintenance/cleanup-images", headers=app_headers())
    assert_error(result, 403, "permission_denied")
    result = request("POST", f"{base_url}/api/maintenance/cleanup-images", headers=admin_headers())
    assert_equal(result.status, 200, "maintenance cleanup status")
    assert_equal(result.json()["enabled"], False, "maintenance cleanup disabled by default")
    print("OK maintenance cleanup auth")

    bad_body, bad_content_type = multipart_body("bad.txt", "text/plain", b"not an image")
    result = request(
        "POST",
        f"{base_url}{UPLOAD_PATH}",
        headers={"Upload-Token": UPLOAD_TOKEN, "Content-Type": bad_content_type},
        body=bad_body,
    )
    assert_error(result, 400, "unsupported_file_type")
    print("OK unsupported file type")

    result = upload(base_url, "fake.png", "image/png", b"not an image")
    assert_error(result, 400, "unsupported_file_type")
    print("OK image header validation")

    large_png = b"\x89PNG\r\n\x1a\n" + (b"0" * (10 * 1024 * 1024 + 1))
    result = upload(base_url, "large.png", "image/png", large_png)
    assert_error(result, 413, "file_too_large")
    print("OK file too large")

    result = request(
        "POST",
        f"{base_url}{UPLOAD_PATH}",
        headers={"Content-Type": "image/png"},
        body=PNG_BYTES,
    )
    assert_equal(result.status, 200, "raw upload status")
    assert_equal(result.json()["status"], "pending", "raw upload status body")
    print("OK raw image upload")

    result = upload(base_url, "ticket.png", "image/png", PNG_BYTES)
    assert_equal(result.status, 200, "upload status")
    upload_payload = result.json()
    expense_id = int(upload_payload["id"])
    assert_equal(upload_payload["status"], "pending", "upload status body")
    print("OK upload screenshot")

    result = request("GET", f"{base_url}/api/expenses/pending", headers=app_headers())
    assert_equal(result.status, 200, "pending status")
    pending_items = result.json()
    uploaded = next(item for item in pending_items if item["id"] == expense_id)
    image_path = uploaded["image_path"]
    assert_true(image_path.startswith("uploads/"), "image path should be relative")
    assert_true(":" not in image_path and "\\" not in image_path, "image path must not expose Windows path")
    assert_true(
        uploaded["thumbnail_path"] is None or uploaded["thumbnail_path"].startswith("uploads/"),
        "thumbnail path should be relative",
    )
    assert_true(uploaded["image_hash"], "image hash should be saved")
    print("OK pending query")

    manual_body = json.dumps(
        {
            "amount_cents": 1280,
            "merchant": "手动早餐",
            "category": "吃饭",
            "note": "上班路上",
            "expense_time": "2026-05-04T00:30:00Z",
            "tags": "手动",
            "value_score": 4,
            "regret_score": 1,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    result = request(
        "POST",
        f"{base_url}/api/expenses/manual",
        headers={**app_headers(), "Content-Type": "application/json"},
        body=manual_body,
    )
    assert_equal(result.status, 200, "manual create status")
    manual_expense = result.json()
    assert_equal(manual_expense["status"], "confirmed", "manual create confirmed")
    assert_equal(manual_expense["category"], "餐饮", "manual create category alias")
    assert_equal(manual_expense["source"], "手动记账", "manual create source")
    assert_true(manual_expense["confirmed_at"].endswith("Z"), "manual confirmed_at should be ISO UTC")
    result = request(
        "POST",
        f"{base_url}/api/expenses/manual",
        headers={**app_headers(), "Content-Type": "application/json"},
        body=b'{"merchant":"missing amount"}',
    )
    assert_error(result, 400, "amount_required")
    print("OK manual expense create")

    result = request("GET", f"{base_url}/api/settings/server", headers=app_headers())
    assert_equal(result.status, 200, "server settings status")
    server_settings = result.json()
    assert_equal(server_settings["account_name"], "我", "server settings account name")
    assert_equal(server_settings["ledger_name"], "我的小票夹", "server settings ledger name")
    assert_equal(server_settings["device_name"], "smoke-android", "server settings device name")
    assert_equal(server_settings["role"], "owner", "server settings role")
    assert_equal(server_settings["status"], "ok", "server settings status value")
    assert_equal(server_settings["storage_status"], "normal", "server settings storage status")
    assert_true(server_settings["pending_count"] >= 1, "server settings pending count")
    assert_true(server_settings["confirmed_count"] >= 1, "server settings confirmed count")
    assert_true(server_settings["upload_storage_bytes"] > 0, "server settings upload storage")
    assert_true(server_settings["latest_upload_at"].endswith("Z"), "server settings latest upload")
    assert_true("max_upload_size_mb" not in server_settings, "server settings must not expose upload limit")
    assert_true("ocr_provider" not in server_settings, "server settings must not expose ocr provider")
    assert_true(
        "delete_image_after_confirm" not in server_settings,
        "server settings must not expose cleanup config",
    )
    assert_true("token" not in json.dumps(server_settings).lower(), "server settings must not expose token")
    print("OK server settings")

    result = request("GET", f"{base_url}/api/expenses/{expense_id}/image")
    assert_error(result, 401, "invalid_token")
    print("OK protected image requires token")

    result = request("GET", f"{base_url}/api/expenses/{expense_id}/image", headers=app_headers())
    assert_equal(result.status, 200, "image status")
    assert_equal(result.body, PNG_BYTES, "image body")
    print("OK protected image")

    result = request("GET", f"{base_url}/api/expenses/{expense_id}/thumbnail", headers=app_headers())
    assert_equal(result.status, 200, "thumbnail status")
    assert_true(result.body.startswith(b"\xff\xd8"), "thumbnail should be jpeg")
    print("OK protected thumbnail")

    pre_confirm_snapshot = request(
        "GET",
        f"{base_url}/api/expenses/{expense_id}",
        headers=app_headers(),
    )
    assert_equal(pre_confirm_snapshot.status, 200, "pre-confirm snapshot status")
    confirm_no_amount_body = json.dumps(
        {"expected_updated_at": pre_confirm_snapshot.json()["updated_at"]},
        ensure_ascii=False,
    ).encode("utf-8")
    result = request(
        "POST",
        f"{base_url}/api/expenses/{expense_id}/confirm",
        headers={**app_headers(), "Content-Type": "application/json"},
        body=confirm_no_amount_body,
    )
    assert_error(result, 400, "amount_required")
    print("OK amount required")

    snapshot = request(
        "GET",
        f"{base_url}/api/expenses/{expense_id}",
        headers=app_headers(),
    )
    assert_equal(snapshot.status, 200, "patch snapshot status")
    update_body = json.dumps(
        {
            "amount_cents": 3680,
            "merchant": "美团外卖",
            "category": "餐饮",
            "note": "午饭",
            "expense_time": "2026-05-03T04:20:00Z",
            "expected_updated_at": snapshot.json()["updated_at"],
        },
        ensure_ascii=False,
    ).encode("utf-8")
    result = request(
        "PATCH",
        f"{base_url}/api/expenses/{expense_id}",
        headers={**app_headers(), "Content-Type": "application/json"},
        body=update_body,
    )
    assert_equal(result.status, 200, "patch status")
    patched = result.json()
    assert_equal(patched["amount_cents"], 3680, "patched amount")
    assert_equal(patched["merchant"], "美团外卖", "patched merchant")
    assert_equal(patched["category"], "餐饮", "patched category")
    assert_true(patched["expense_time"].endswith("Z"), "expense time should be ISO UTC")
    print("OK patch expense")

    # OCR_PROVIDER=empty 下 retry 必须 503 ocr_not_configured（fact-backed contract，
    # 见 backend/app/services/expense_service/_ocr.py:retry_expense_ocr 与 ADR-0021）。
    retry_body = json.dumps(
        {"expected_updated_at": patched["updated_at"]},
        ensure_ascii=False,
    ).encode("utf-8")
    result = request(
        "POST",
        f"{base_url}/api/expenses/{expense_id}/ocr/retry",
        headers={**app_headers(), "Content-Type": "application/json"},
        body=retry_body,
    )
    assert_error(result, 503, "ocr_not_configured")
    print("OK ocr retry refuses empty provider")

    recognize_upload = upload(base_url, "recognize.png", "image/png", PNG_BYTES)
    assert_equal(recognize_upload.status, 200, "recognize upload status")
    recognize_id = int(recognize_upload.json()["id"])
    # ADR-0038 PR-2e: recognize-text now requires ``expected_updated_at``;
    # snapshot the freshly uploaded row's ``updated_at`` and ship it.
    recognize_snapshot = wait_for_expense_thumbnail(
        base_url,
        recognize_id,
        "recognize",
    )
    recognize_body = json.dumps(
        {
            "expected_updated_at": recognize_snapshot["updated_at"],
            "raw_text": "\n".join(
                [
                    "中国建设银行",
                    "交易提醒",
                    "交易时间：2026年5月4日 16:23:25",
                    "交易金额：18.51（人民币）",
                ]
            ),
        },
        ensure_ascii=False,
    ).encode("utf-8")
    result = request(
        "POST",
        f"{base_url}/api/expenses/{recognize_id}/recognize-text",
        headers={**app_headers(), "Content-Type": "application/json"},
        body=recognize_body,
    )
    assert_equal(result.status, 200, "recognize text status")
    recognized = result.json()
    assert_equal(recognized["amount_cents"], 1851, "recognized amount")
    assert_equal(recognized["merchant"], "中国建设银行", "recognized merchant")
    assert_equal(recognized["expense_time"], "2026-05-04T08:23:25Z", "recognized time")
    print("OK recognize text")

    confirm_snapshot = request(
        "GET",
        f"{base_url}/api/expenses/{expense_id}",
        headers=app_headers(),
    )
    assert_equal(confirm_snapshot.status, 200, "confirm snapshot status")
    confirm_body = json.dumps(
        {"expected_updated_at": confirm_snapshot.json()["updated_at"]},
        ensure_ascii=False,
    ).encode("utf-8")
    result = request(
        "POST",
        f"{base_url}/api/expenses/{expense_id}/confirm",
        headers={**app_headers(), "Content-Type": "application/json"},
        body=confirm_body,
    )
    assert_equal(result.status, 200, "confirm status")
    confirmed = result.json()
    assert_equal(confirmed["status"], "confirmed", "confirmed status")
    assert_true(confirmed["confirmed_at"].endswith("Z"), "confirmed_at should be ISO UTC")
    print("OK confirm expense")

    result = request(
        "GET",
        f"{base_url}/api/expenses/confirmed?page=1&page_size=50&month=2026-05&category=%E5%90%83%E9%A5%AD",
        headers=app_headers(),
    )
    assert_equal(result.status, 200, "confirmed list status")
    confirmed_page = result.json()
    assert_equal(confirmed_page["page"], 1, "confirmed page")
    assert_equal(confirmed_page["page_size"], 50, "confirmed page size")
    assert_true(confirmed_page["total"] >= 1, "confirmed total")
    assert_true(any(item["id"] == expense_id for item in confirmed_page["items"]), "confirmed item included")
    print("OK confirmed pagination")

    result = request("GET", f"{base_url}/api/expenses/categories", headers=app_headers())
    assert_equal(result.status, 200, "categories status")
    assert_true("餐饮" in result.json()["items"], "categories include default")
    assert_true("吃饭" not in result.json()["items"], "categories hide legacy alias")
    print("OK categories")

    result = request("GET", f"{base_url}/api/expenses/months", headers=app_headers())
    assert_equal(result.status, 200, "months status")
    assert_true("2026-05" in result.json()["items"], "months include confirmed month")
    print("OK months")

    result = request(
        "GET",
        f"{base_url}/api/expenses/export.csv?month=2026-05&category=%E5%90%83%E9%A5%AD",
        headers=app_headers(),
    )
    assert_equal(result.status, 200, "csv export status")
    csv_text = result.body.decode("utf-8-sig")
    assert_true("美团外卖" in csv_text and "3680" in csv_text, "csv export content")
    print("OK csv export")

    result = request("GET", f"{base_url}/api/stats/monthly?month=2026-05", headers=app_headers())
    assert_equal(result.status, 200, "stats status")
    stats = result.json()
    assert_equal(stats["total_amount_cents"], 4960, "stats total")
    assert_equal(stats["count"], 2, "stats count")
    assert_equal(stats["by_category"][0]["category"], "餐饮", "stats category")
    print("OK monthly stats")

    result = request("GET", f"{base_url}/api/rules/categories", headers=app_headers())
    assert_equal(result.status, 200, "rules list status")
    assert_true(any(rule["keyword"] == "OpenAI" for rule in result.json()), "default rules seeded")
    print("OK category rules list")

    rule_body = json.dumps(
        {"keyword": "测试商家", "category": "生活", "enabled": True, "priority": 1},
        ensure_ascii=False,
    ).encode("utf-8")
    result = request(
        "POST",
        f"{base_url}/api/rules/categories",
        headers={**app_headers(), "Content-Type": "application/json"},
        body=rule_body,
    )
    assert_equal(result.status, 200, "rule create status")
    rule = result.json()
    rule_id = int(rule["id"])
    patch_rule_body = json.dumps(
        {"priority": 2, "expected_updated_at": rule["updated_at"]},
        ensure_ascii=False,
    ).encode("utf-8")
    result = request(
        "PATCH",
        f"{base_url}/api/rules/categories/{rule_id}",
        headers={**app_headers(), "Content-Type": "application/json"},
        body=patch_rule_body,
    )
    assert_equal(result.status, 200, "rule patch status")
    patched_rule = result.json()
    assert_equal(patched_rule["priority"], 2, "rule patched priority")
    delete_rule_body = json.dumps(
        {"expected_updated_at": patched_rule["updated_at"]},
        ensure_ascii=False,
    ).encode("utf-8")
    result = request(
        "DELETE",
        f"{base_url}/api/rules/categories/{rule_id}",
        headers={**app_headers(), "Content-Type": "application/json"},
        body=delete_rule_body,
    )
    assert_equal(result.status, 200, "rule delete status")
    assert_equal(result.json()["status"], "ok", "rule delete response")
    print("OK category rule create patch delete")

    second_upload = upload(base_url, "ticket2.png", "image/png", PNG_BYTES)
    assert_equal(second_upload.status, 200, "second upload status")
    second_id = int(second_upload.json()["id"])
    result = request("GET", f"{base_url}/api/duplicates", headers=app_headers())
    assert_equal(result.status, 200, "duplicates status")
    duplicates = result.json()
    assert_true(any(item["id"] == second_id for item in duplicates), "duplicate should be suspected")
    print("OK duplicate detection")

    second_snapshot = wait_for_expense_thumbnail(
        base_url,
        second_id,
        "second patch",
    )
    second_update_body = json.dumps(
        {
            "amount_cents": 2000,
            "merchant": "OpenAI",
            "note": "订阅",
            "expense_time": "2026-05-04T04:20:00Z",
            "expected_updated_at": second_snapshot["updated_at"],
        },
        ensure_ascii=False,
    ).encode("utf-8")
    result = request(
        "PATCH",
        f"{base_url}/api/expenses/{second_id}",
        headers={**app_headers(), "Content-Type": "application/json"},
        body=second_update_body,
    )
    assert_equal(result.status, 200, "second patch status")
    assert_equal(result.json()["category"], "AI订阅", "auto classified category")
    print("OK auto classification")

    second_mnd_snapshot = request(
        "GET",
        f"{base_url}/api/expenses/{second_id}",
        headers=app_headers(),
    )
    assert_equal(second_mnd_snapshot.status, 200, "mark-not-duplicate snapshot status")
    second_mnd_body = json.dumps(
        {"expected_updated_at": second_mnd_snapshot.json()["updated_at"]},
        ensure_ascii=False,
    ).encode("utf-8")
    result = request(
        "POST",
        f"{base_url}/api/expenses/{second_id}/mark-not-duplicate",
        headers={**app_headers(), "Content-Type": "application/json"},
        body=second_mnd_body,
    )
    assert_equal(result.status, 200, "mark not duplicate status")
    assert_equal(result.json()["duplicate_status"], "none", "duplicate cleared")
    print("OK mark not duplicate")

    similar_upload = upload(base_url, "ticket4.png", "image/png", PNG_BYTES)
    assert_equal(similar_upload.status, 200, "similar upload status")
    similar_id = int(similar_upload.json()["id"])
    similar_mnd_snapshot = wait_for_expense_thumbnail(
        base_url,
        similar_id,
        "similar mark-not-duplicate",
    )
    similar_mnd_body = json.dumps(
        {"expected_updated_at": similar_mnd_snapshot["updated_at"]},
        ensure_ascii=False,
    ).encode("utf-8")
    result = request(
        "POST",
        f"{base_url}/api/expenses/{similar_id}/mark-not-duplicate",
        headers={**app_headers(), "Content-Type": "application/json"},
        body=similar_mnd_body,
    )
    assert_equal(result.status, 200, "similar clear hash duplicate")
    similar_snapshot = request(
        "GET",
        f"{base_url}/api/expenses/{similar_id}",
        headers=app_headers(),
    )
    assert_equal(similar_snapshot.status, 200, "similar patch snapshot status")
    similar_update_body = json.dumps(
        {
            "amount_cents": 2000,
            "merchant": "OpenAI",
            "expense_time": "2026-05-04T05:00:00Z",
            "expected_updated_at": similar_snapshot.json()["updated_at"],
        },
        ensure_ascii=False,
    ).encode("utf-8")
    result = request(
        "PATCH",
        f"{base_url}/api/expenses/{similar_id}",
        headers={**app_headers(), "Content-Type": "application/json"},
        body=similar_update_body,
    )
    assert_equal(result.status, 200, "similar patch status")
    assert_equal(result.json()["duplicate_status"], "suspected", "similar duplicate suspected")
    print("OK similar duplicate detection")

    reject_snapshot = request(
        "GET",
        f"{base_url}/api/expenses/{similar_id}",
        headers=app_headers(),
    )
    assert_equal(reject_snapshot.status, 200, "reject snapshot status")
    reject_body = json.dumps(
        {"expected_updated_at": reject_snapshot.json()["updated_at"]},
        ensure_ascii=False,
    ).encode("utf-8")
    result = request(
        "POST",
        f"{base_url}/api/expenses/{similar_id}/reject",
        headers={**app_headers(), "Content-Type": "application/json"},
        body=reject_body,
    )
    assert_equal(result.status, 200, "reject status")
    assert_equal(result.json()["status"], "rejected", "rejected status")
    print("OK reject expense")

    second_confirm_snapshot = request(
        "GET",
        f"{base_url}/api/expenses/{second_id}",
        headers=app_headers(),
    )
    assert_equal(second_confirm_snapshot.status, 200, "second confirm snapshot status")
    second_confirm_body = json.dumps(
        {"expected_updated_at": second_confirm_snapshot.json()["updated_at"]},
        ensure_ascii=False,
    ).encode("utf-8")
    result = request(
        "POST",
        f"{base_url}/api/expenses/{second_id}/confirm",
        headers={**app_headers(), "Content-Type": "application/json"},
        body=second_confirm_body,
    )
    assert_equal(result.status, 200, "second confirm status")
    print("OK second confirm")



def main() -> int:
    clean_smoke_runtime()
    port = free_port()
    base_url = f"http://{HOST}:{port}"
    process = start_server(port)
    try:
        wait_for_server(base_url, process)
        run_smoke(base_url)
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        clean_smoke_runtime()


if __name__ == "__main__":
    raise SystemExit(main())
