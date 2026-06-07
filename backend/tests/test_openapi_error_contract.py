"""OpenAPI must describe the real project error envelope.

FastAPI's generated schema defaults validation failures to ``HTTPValidationError``,
but this app converts runtime errors (including validation failures) to the
project envelope ``{"error": "...", "message": "...", ...}``. Android error
decoding and the DTO contract gate depend on that shape being visible in the
committed OpenAPI snapshot.
"""

from __future__ import annotations

from app.main import app

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
ERROR_REF = {"$ref": "#/components/schemas/ErrorResponse"}


def _is_project_api_path(path: str) -> bool:
    return path.startswith("/api/") or path.startswith("/u/")


def test_api_openapi_responses_use_project_error_envelope() -> None:
    app.openapi_schema = None
    spec = app.openapi()
    error_schema = spec["components"]["schemas"]["ErrorResponse"]
    assert {
        "error",
        "message",
        "request_id",
        "conflict_tag_public_id",
        "conflict_tag_row_version",
    }.issubset(error_schema["properties"])

    checked = 0
    for path, path_item in spec["paths"].items():
        if not _is_project_api_path(path):
            continue
        for method, operation in path_item.items():
            if method not in HTTP_METHODS:
                continue
            checked += 1
            responses = operation["responses"]
            assert responses["422"]["content"]["application/json"]["schema"] == ERROR_REF
            assert responses["default"]["content"]["application/json"]["schema"] == ERROR_REF
            assert "HTTPValidationError" not in repr(responses), f"{method.upper()} {path}"

    assert checked > 0
