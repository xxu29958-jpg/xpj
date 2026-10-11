"""The selected common owners and small, exact reviewed independent boundaries."""

from __future__ import annotations

import ast
import re

from error_reporting_rules import aliases_for, calls, function_nodes, kotlin_code

ANDROID = "android/app/src/main/java/com/ticketbox/"
PYTHON_OWNERS = {
    "backend/app/errors.py": {
        "app_error_handler": {"app.error_reporting.retain_handled_error"},
        "http_error_handler": {"app.error_reporting.retain_handled_error"},
        "unhandled_error_handler": {"app.error_reporting.report_http_error"},
    },
    "backend/app/middleware/logging.py": {
        "SanitizedLoggingMiddleware.dispatch": {"app.error_reporting.report_http_error"},
    },
    "backend/app/error_reporting.py": {
        "report_http_error": {"report_error"}, "report_error": {"logger.error"},
    },
    "backend/app/services/background_task_executor.py": {
        "submit_committed": {"app.error_reporting.report_error"},
        "_report_worker_outcome": {"app.error_reporting.report_error", "future.exception", "future.cancelled"},
        "_ExecutorPool.submit": {"runner", "concurrent.futures.ThreadPoolExecutor.submit", "future.add_done_callback", "_report_worker_outcome"},
    },
    "backend/app/services/background_task_worker.py": {"run_task": {"app.error_reporting.report_error"}},
    "backend/app/log_sanitize.py": {
        "SanitizedFormatter.format": {"sanitize_log_text", "safe_exception_text"},
        "SanitizedFormatter.__init__": {"app.diagnostic_identity.diagnostic_build_identity"},
    },
    "backend/packaging/launch.py": {"main": {"logging.config.dictConfig", "_build_log_config"}},
}
KOTLIN_OWNERS = (
    ANDROID + "data/remote/dto/ErrorDto.kt", ANDROID + "data/repository/NetworkErrorHandler.kt",
    ANDROID + "data/repository/NetworkErrorReporting.kt",
)
REQUIRED_FILES = (*PYTHON_OWNERS, *KOTLIN_OWNERS, "android/app/build.gradle.kts")

# Exact-symbol evidence, never a module/directory exemption or a handler registry.
# A changed symbol invalidates this reviewed responsibility and requires a fresh review.
REVIEWED_BOUNDARIES = {
    ("backend/app/services/background_task_executor.py", "_ExecutorPool.submit"): {
        "sha256": "3228d34871e9c9efc391ac6bcd4ea2fbf711dd1e09b8fe4137132484fa137056", "owner": "pool completion reports Future errors; inline errors propagate to submit_committed",
        "test": "backend/tests/test_background_task_claim.py::test_claim_failure_is_observed_without_publishing_a_new_task_state",
        "reason": "The existing pool Future retains outside-handler exceptions. Its completion callback reports them without consuming cancellation or changing task state.",
    },
    ("backend/app/error_reporting.py", "report_error"): {
        "sha256": "846d33fc9a0853f2617085a4fd235523e42239695788f98212c58c9b8fbcaa82", "owner": "final log sink failure stays outside business state",
        "test": "backend/tests/test_error_reporting_runtime.py::test_logging_sink_failure_does_not_replace_http_outcomes",
        "reason": "Only the log call is suppressed; there is no business retry, persistence or recursive reporting.",
    },
    (ANDROID + "data/repository/NetworkErrorHandler.kt", "safeCall"): {
        "sha256": "24a26eb6fdc2b73a1bb99203c808221f7078dc550894d12eac0cefcdbf3bf707", "owner": "public repository failure mapping and sanitized Logcat",
        "test": "android/app/src/test/java/com/ticketbox/data/repository/NetworkErrorReportingTest.kt",
        "reason": "Cancellation reraises and existing RepositoryException is returned; unexpected outcomes are logged before mapping.",
    },
    (ANDROID + "data/repository/NetworkErrorReporting.kt", "logNetworkWarning"): {
        "sha256": "58d8569c1a2ae044feb3eb78064704e73e79e9c6232a9ce11efd2d32f1881e40", "owner": "the existing TicketboxNetwork Logcat output",
        "test": "android/app/src/test/java/com/ticketbox/data/repository/NetworkErrorReportingTest.kt",
        "reason": "Sanitized message plus project frames, with no raw Throwable argument; an output failure cannot change the Result.",
    },
    (ANDROID + "data/repository/RecurringQueryReader.kt", "read"): {
        "sha256": "3fc23c76b1cb3b718259f815af0ee814205430e6d62836aa44ddd71352c34840",
        "owner": "existing NetworkErrorHandler.safeCall and sanitized TicketboxNetwork output",
        "test": "android/app/src/test/java/com/ticketbox/data/repository/RecurringQueryReadTest.kt::storagePublicationFailureKeepsFreshGetButRefusalOrMalformedResponseNeverUsesOldCache",
        "reason": "The broad catch only selects authorized cached reads for transport unavailability. Other errors, cancellation and cache validation failures propagate to the enclosing safeCall; HTTP refusal uses httpFailure before revoking cached access. NetworkErrorReportingTest proves the existing sanitized sink. Alias publication adds no independent terminal owner, retry or user-facing raw exception.",
    },
    (ANDROID + "data/repository/UpdateMerchantAliasDispatcher.kt", "dispatch"): {
        "sha256": "d044a4f8f66ecae3886b6d5b0cde72617fbee7e6f9798e8efc7492fa578b31e3",
        "owner": "existing NetworkErrorHandler HTTP mapping and sanitized TicketboxNetwork Logcat",
        "test": "android/app/src/test/java/com/ticketbox/data/repository/NetworkErrorReportingTest.kt::aliasReplayFailureReportsWithoutSettlingOrRetryingOriginal",
        "reason": "Unexpected replay errors report through logNetworkWarning before a blocking Failure preserves the original key and payload. The user sees no raw exception text; cancellation still propagates and transport retries retain their existing owner.",
    },
    (ANDROID + "data/repository/DebtGoalEditSubmission.kt", "dispatch"): {
        "sha256": "b54c7bcf93c5cf4da626e40f523ddbd1502e37968f14b28c02c47ef706038244",
        "owner": "existing HTTP mapping and sanitized TicketboxNetwork Logcat",
        "test": "android/app/src/test/java/com/ticketbox/data/repository/NetworkErrorReportingTest.kt::debtLinkReplayFailureReportsSafelyAndKeepsItsOriginalCommand",
        "reason": "Transport and unexpected replay failures report through logNetworkWarning without raw exception text in the UI or Logcat. The existing Outbox retains the original selection or date command, key and OCC; unexpected failures do not acknowledge or retry the command, and cancellation propagates.",
    },
    (ANDROID + "data/repository/ConfirmExpenseDispatcher.kt", "dispatch"): {
        "sha256": "d73acd32bcf702f04442fcd1103e419bd9bebcfb7d024eba4e4be0119a0d5a64",
        "owner": "existing HTTP mapping and sanitized TicketboxNetwork Logcat",
        "test": "android/app/src/test/java/com/ticketbox/data/repository/NetworkErrorReportingTest.kt::confirmReplayFailureReportsSafelyAndKeepsItsOriginalCommand",
        "reason": "Unexpected replay errors are reported before a blocking Failure retains the original command, key and OCC. No raw exception text reaches the user; cancellation propagates and the existing transport retry owner is preserved.",
    },
    (ANDROID + "data/repository/ConfirmRecurringCandidateDispatcher.kt", "dispatch"): {
        "sha256": "16eda617eeb4e0d0e924aace3aeec3c90c6da3dab54bca6f7e60f8157e2be7bb",
        "owner": "existing HTTP mapping and sanitized TicketboxNetwork output",
        "test": "android/app/src/test/java/com/ticketbox/data/repository/NetworkErrorReportingTest.kt::candidateReplayFailureReportsSafelyAndKeepsItsOriginalCommand",
        "reason": "Unexpected adoption replay failures report through logNetworkWarning while Outbox retains the original payload and key as unresolved. Receipt mismatches use a static diagnostic. No raw exception text reaches the UI; cancellation propagates and existing transport retry behavior is unchanged.",
    },
    (ANDROID + "data/repository/ApplyConfirmedRulesDispatcher.kt", "dispatch"): {
        "sha256": "05c182564cf7ba8c855da84ad741a40e11473d5bcb5fb47d8e53a77404ce2a65",
        "owner": "NetworkErrorHandler for read/HTTP errors; sanitized TicketboxNetwork output for unexpected replay failures",
        "test": "android/app/src/test/java/com/ticketbox/data/repository/RuleApplicationCommandTest.kt",
        "reason": "A verified first receipt survives a later read failure or cancellation with a retained read-recovery flag. Repository read failures already use NetworkErrorHandler; unexpected callback and replay faults use logNetworkWarning without raw messages, changing keys, retrying or claiming acceptance.",
    },
    (ANDROID + "data/repository/SaveMonthlyBudgetDispatcher.kt", "dispatch"): {
        "sha256": "456969319e417619bf74dcafe9b254abd21dcf565d2727337e65626568c679bb",
        "owner": "existing HTTP mapping and sanitized TicketboxNetwork output for read cleanup/replay faults",
        "test": "android/app/src/test/java/com/ticketbox/data/repository/SaveMonthlyBudgetDispatcherTest.kt",
        "reason": "Verified budget acceptance remains final when read cleanup fails; unexpected failures report through logNetworkWarning and retain the first receipt or unresolved original as appropriate. Cancellation before acceptance propagates; after acceptance only read repair remains. No raw exception text enters the UI or Logcat.",
    },
    (ANDROID + "viewmodel/OriginalAttachmentViewModel.kt", "loadSelectedImage"): {
        "sha256": "af13ab245557b90c219f3460be1b1b3e04cf8ab8636f179ca4b531fdc9f9e8f4",
        "owner": "existing sanitized TicketboxNetwork output and original selection presentation",
        "test": "android/app/src/test/java/com/ticketbox/viewmodel/OriginalAttachmentViewModelTest.kt::firstAttachmentSelectionRestoresOriginalBillAndKeyWithoutFinancialCreation",
        "reason": "Local source read failures report a fixed operation label through logNetworkWarning, whose existing NetworkErrorReportingTest proves the sanitized sink. The UI uses a resource without provider exception text; original URI, key, payload and displayed bytes remain available for retry. File retention and reload use the existing safeCall owner; only a durable descriptor enables admission. Cancellation propagates, and a changed binding cannot receive the image or error.",
    },
    ("backend/app/routes/web_expense_recognition.py", "web_recognition_post"): {
        "sha256": "3deb3d71c61d1cacd6987fffa263f4f784e49269a07e0a5ed2083db075169632",
        "owner": "retain_handled_error feeds the common HTTP reporter while preserving the original form",
        "test": "backend/tests/test_web_recognition_runtime.py::test_recognition_failure_preserves_original_and_reports_through_http_owner",
        "reason": "Text and image consumers share the original OCR commands. Expected 4xx refusals preserve input; 5xx/SQL failures roll back and retain the exception for the common HTTP reporter. Native and JSON responses preserve the original identity, key and version without exposing the cause or acknowledging a failed command.",
    },
    ("backend/packaging/launch.py", "_build_log_config"): {
        "sha256": "e2e66d7e5752900a201b3cd2c9b9b18c4d969dc095b7ae327c3fe18b88f551ee", "owner": "existing shared rotating file and optional console handlers",
        "test": "backend/tests/test_error_reporting_runtime.py::test_rotated_files_keep_build_identity_and_final_sanitization",
        "reason": "All configured root/Uvicorn handlers use the common formatter; the existing 5MB and three backups stay unchanged.",
    },
}


def violation(path: str, symbol: str, detail: str, line: int = 1) -> dict:
    return {"status": "VIOLATION", "rule": "common-owner", "path": path, "symbol": symbol,
        "line": line, "observation": detail, "owner": "existing shared error reporting"}


def _python_contract(path: str, text: str) -> list[dict]:
    tree = ast.parse(text, filename=path)
    functions, aliases = function_nodes(tree), aliases_for(tree)
    results = []
    for symbol, required in PYTHON_OWNERS[path].items():
        node = functions.get(symbol)
        missing = required - (calls(node, aliases) if node else set())
        if missing:
            results.append(violation(path, symbol, "missing shared calls: " + ", ".join(sorted(missing)),
                node.lineno if node else 1))
    if path == "backend/packaging/launch.py":
        config = functions.get("_build_log_config")
        entries = {key.value: value.value for node in ast.walk(config or tree) if isinstance(node, ast.Dict)
            for key, value in zip(node.keys, node.values, strict=True)
            if isinstance(key, ast.Constant) and isinstance(value, ast.Constant)}
        expected = {"()": "app.log_sanitize.SanitizedFormatter", "maxBytes": 5_000_000, "backupCount": 3}
        for key, value in expected.items():
            if entries.get(key) != value:
                results.append(violation(path, "_build_log_config", f"final formatter/rotation changed: {key}"))
    return results


def _android_contract(files: dict[str, str]) -> list[dict]:
    handler_path, reporting_path = KOTLIN_OWNERS[1:3]
    handler, output = kotlin_code(files[handler_path]), kotlin_code(files[reporting_path])
    results = []
    checks = [
        (KOTLIN_OWNERS[0], "requestId", "requestId" in kotlin_code(files[KOTLIN_OWNERS[0]])),
        (handler_path, "parseErrorMessage", bool(re.search(r"requestId\s*=\s*bodyId\s*\?:\s*headerId", handler))),
        (handler_path, "parseErrorMessage", bool(re.search(r"\.copy\(\s*requestId\s*=\s*requestId\s*\)", handler))),
        (handler_path, "safeCall", "BuildConfig.DEBUG" not in handler and "logNetworkWarning" in handler),
        (handler_path, "parseHttpError", handler.count(".string()") == 1),
        (reporting_path, "logNetworkWarning", bool(re.search(r"Log\.w\(\s*,\s*output\s*\)", output))),
        (reporting_path, "logNetworkWarning", all(item in output for item in (
            "BuildConfig.SOURCE_FINGERPRINT", "sanitizedDiagnosticText(message)", "projectFrames(current.stackTrace)"))),
        ("android/app/build.gradle.kts", "SOURCE_FINGERPRINT", 'buildConfigField("String", "SOURCE_FINGERPRINT"' in files["android/app/build.gradle.kts"]),
    ]
    for path, symbol, okay in checks:
        if not okay:
            results.append(violation(path, symbol, "selected Android decode/output/build wiring regressed"))
    return results


def common_contract(files: dict[str, str]) -> list[dict]:
    for path in REQUIRED_FILES:
        if path not in files:
            raise ValueError(f"required reporting source missing: {path}")
    return [item for path in PYTHON_OWNERS for item in _python_contract(path, files[path])] + _android_contract(files)
