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
        "_ExecutorPool.submit": {"runner", "self._dispatch", "concurrent.futures.ThreadPoolExecutor"},
        "_ExecutorPool._dispatch": {"concurrent.futures.ThreadPoolExecutor.submit", "future.add_done_callback", "self._finished"},
        "_ExecutorPool._finished": {"_report_worker_outcome", "self._dispatch", "app.error_reporting.report_error"},
    },
    "backend/app/services/ocr_worker_client.py": {
        "OcrWorkerClient._read": {"app.error_reporting.report_error", "messages.put_nowait"},
        "OcrWorkerClient._idle_stop": {"app.error_reporting.report_error", "self._stop"},
    },
    "backend/app/services/background_task_worker.py": {"run_task": {"app.error_reporting.report_error"}},
    "backend/app/services/background_task_recovery_service.py": {"_recovery_loop": {"app.error_reporting.report_error"}},
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
    ("backend/app/services/background_task_recovery_service.py", "start_ocr_task_recovery"): {
        "sha256": "eaa02c69cf64125e3818900a1ef07e1fab6c530f5bb486f856e4b462d6309293",
        "owner": "the owned recovery loop and existing sanitized backend logger",
        "test": "backend/tests/test_ocr_task_automatic_recovery.py::test_owned_scanner_reports_failure_and_only_retries_database_errors",
        "reason": "The actual scanner thread reports transient database errors and continues discovery after its bounded wait. Unexpected scan errors report once through the same sink and terminate the scanner without an unhandled thread exception or an automatic programming-error loop. The real-thread counterexample covers both paths; no task receipt, retry budget, input or financial state is rewritten by this terminal boundary. The common contract requires the loop to retain its shared reporting call.",
    },
    (ANDROID + "data/local/LocalSettingsStore.kt", "writeNotificationCaptureFailure"): {
        "sha256": "c35a4e431bac4724b40011c35135bfae44ac23ca21dc2fe979ad4cd570dfa4a2",
        "owner": "existing sanitized TicketboxNetwork output and Settings persistence-failure state",
        "test": "android/app/src/test/java/com/ticketbox/notification/NotificationAdmissionFailureTest.kt::failedPreferenceCommitRemainsVisibleInProcessAndDiagnosticsContainNoCaptureContent",
        "reason": "Synchronous preference write failures report through logNetworkWarning with a fixed operation label and the original authority's SHA-256 scope. The shared sink excludes raw exception messages and private notification contents. Returning false keeps an in-process persistence-failed reminder, and failed acknowledgement retains the original reminder; neither path claims durable success or changes the admitted Outbox intent. The existing failure and acknowledgement tests verify these outcomes and the sanitized diagnostic.",
    },
    (ANDROID + "data/repository/DebtKindPayload.kt", "dispatch"): {
        "sha256": "31f712e15de8efa6659eabf0ea5e8ff536bad1a3e1046d070916a7010371407a",
        "owner": "existing typed DispatchResult and durable Outbox failure/receipt owner",
        "test": "android/app/src/test/java/com/ticketbox/data/repository/DebtKindIntentTest.kt",
        "reason": "The dispatcher reads the original wire payload through the same admission validation used by its UI description. Only that accessor changed; every catch and result branch is unchanged. Cancellation propagates, transport interruption remains retryable, HTTP failures retain the existing mapper, and unverified responses produce the same static blocking failure stored by Outbox. No raw exception text, fresh key, refreshed OCC or success receipt is introduced. The existing replay/binding/refusal tests exercise the retained original consumer.",
    },
    (ANDROID + "data/repository/MonthlyArrangementRepository.kt", "arrangement"): {
        "sha256": "8f2392cfbdd17f024dbf97fba0c34d332710045e0ad5290cb6315c0eb1de76eb",
        "owner": "existing NetworkErrorHandler.safeCall and retained bound cache/read Result",
        "test": "android/app/src/androidTest/java/com/ticketbox/data/repository/MonthlyArrangementRoomContinuityTest.kt",
        "reason": "The saved arrangement and response now share canonical domain values with their original JSON fields; only identity copies disappear. The existing ledger/month/currency validation and snapshot gate still precede exposure. HTTP refusal withdraws access, only transport unavailability admits the already authorized cache, and malformed JSON, cancellation and publication failures still propagate through NetworkErrorHandler.safeCall.",
    },
    (ANDROID + "data/repository/OutboxDrainWorker.kt", "doWork"): {
        "sha256": "321bf7e97e05fa81946e9899ec390d9115d79c2be0560a40c761b7160ecee876",
        "owner": "existing WorkManager outcome and fixed Logcat boundary; per-row failures remain owned by Outbox",
        "test": "android/app/src/test/java/com/ticketbox/data/repository/OutboxDrainWorkerTest.kt",
        "reason": "The runtime compatibility provider moved from AppContainer to OutboxRuntimeCompatibility. Fixed startup/session warnings contain no private inputs; compatibility/drain exceptions now use the existing logNetworkWarning sanitizer instead of handing a raw throwable to Log.w. NetworkErrorReportingTest verifies this shared sink. The referenced worker tests cover failed compatibility, blocked writes, mixed outcomes and cancellation. WorkManager retry classification and original commands are unchanged.",
    },
    (ANDROID + "data/repository/RecordDebtAdjustmentDispatcher.kt", "dispatch"): {
        "sha256": "c8b235102470554b761ab07aa715234b7509dcecea9a453c87997caee67ba71f",
        "owner": "existing typed DispatchResult and durable Outbox failure/receipt owner",
        "test": "android/app/src/test/java/com/ticketbox/data/repository/DebtAdjustmentRepositoryTest.kt",
        "reason": "The dispatcher reads the original wire payload through the same admission validation used by its UI description. Only that accessor changed; every catch and result branch is unchanged. Cancellation propagates, transport interruption remains retryable, HTTP failures retain the existing mapper, and unverified responses produce the same static blocking failure stored by Outbox. No raw exception text, fresh key, refreshed OCC or success receipt is introduced. The existing replay/binding/refusal tests exercise the retained original consumer.",
    },
    (ANDROID + "data/repository/RecordDebtRepaymentDispatcher.kt", "dispatch"): {
        "sha256": "b2ad7ce6131c54849d2615ef379f7aeb82a9e6d755e5cd9a994f54594e95faac",
        "owner": "existing typed DispatchResult and durable Outbox failure/receipt owner",
        "test": "android/app/src/test/java/com/ticketbox/data/repository/DirectRepaymentIntentTest.kt",
        "reason": "The dispatcher reads the original wire payload through the same admission validation used by its UI description. Only that accessor changed; every catch and result branch is unchanged. Cancellation propagates, transport interruption remains retryable, HTTP failures retain the existing mapper, and unverified responses produce the same static blocking failure stored by Outbox. No raw exception text, fresh key, refreshed OCC or success receipt is introduced. The existing replay/binding/refusal tests exercise the retained original consumer.",
    },
    ("desktop/backend_manager/connector_control.py", "ConnectorControl.start"): {
        "sha256": "7bd3df2bda00d8c3707dc6b698db8033ed6467052745441ae6432bcabf72ce45",
        "owner": "ConnectorControl._run and the existing Manager action status",
        "test": "desktop/tests/test_connector_control.py::test_worker_reports_unexpected_failure_without_leaking_or_repeating",
        "reason": "The one finite worker enters _run, which observes failures in both the action and its final refresh. Known action results keep their existing owner; an unexpected terminal failure produces a static unknown status with refresh/diagnostic guidance. The real-thread regression proves termination, one host request, released mutation state and no uncaught thread exception or private stderr. No new request or automatic retry is created.",
    },
    ("desktop/backend_manager/connector_control.py", "ConnectorControl._run"): {
        "sha256": "6ea2f1aa084ff1d92d895b96a89ab63014b61099d09bbee3a4e0926a0a246e7d",
        "owner": "existing Manager action status; durable host result remains owned by Lifecycle",
        "test": "desktop/tests/test_connector_control.py::test_worker_reports_unexpected_failure_without_leaking_or_repeating",
        "reason": "This is the terminal owner of the fixed connector worker, including exceptions from final refresh. It exposes only a static unknown result and next step, never exception text, a false success, or another operation. The regression injects a private marker both during the action and after the host reply and verifies the real thread cannot leak it through stderr or remain running.",
    },
    ("distribution/windows/lifecycle/ticketbox_lifecycle/cli.py", "_install_main"): {
        "sha256": "0a8ca6769a8c8dac3c7c9e58bd36dbdf5995dfa4955ef4b3090d44a7e59ab148",
        "owner": "existing Lifecycle private result file and sanitized CLI stderr",
        "test": "distribution/windows/tests/test_cli.py::test_unhandled_failure_does_not_publish_exception_text",
        "reason": "CLI retains request parsing and terminal output while the domain owns committed-operation finalization. Unexpected failures still become static unhandled/failed_recoverable results and pass once through command_io.emit_failure. The regression checks the result, empty stdout, one sanitized stderr line and absence of the private exception marker; no alternate recovery path is added.",
    },
    ("distribution/windows/lifecycle/ticketbox_lifecycle/domain/operation.py", "finalize_install_result"): {
        "sha256": "3709ef79a7a1f6c256e3c3e583727057abc9e3ea906d5b36a6028505736c387d",
        "owner": "existing Lifecycle committed-operation delivery and command_io failure output",
        "test": "distribution/windows/tests/test_install_sequence.py::test_archive_failure_retains_exact_commit_and_reports_once",
        "reason": "Exact-commit validation and archival now belong to the operation domain. CLI writes the returned result and reports failure once. An archive failure still returns operation_archive_failed without claiming successful delivery, repeating the operation or removing its exact active commit. The regression invokes the real CLI, injects an archive failure and verifies one attempt, retained authority, the private failure result and one sanitized stderr report with no pairing code. It does not add an archive retry or a new reporting path.",
    },
    ("distribution/windows/lifecycle/ticketbox_lifecycle/domain/restore.py", "_restore_candidate"): {
        "sha256": "2fab1d47a8e99d77eb6e436b5d0d07d5913924924aee14ab7beddbbb1ef6b54a",
        "owner": "existing Lifecycle failed-operation result, private result file and sanitized CLI stderr",
        "test": "distribution/windows/tests/test_cold_restore_coordinator.py::test_unexpected_restore_failure_uses_existing_terminal_report_without_private_input",
        "reason": "The bounded coordinator moved from restore_cli to domain.restore and fences Backend through the shared domain.operation owner. Known lifecycle codes survive; unknown errors still become the static restore_incomplete result so recovery credentials cannot reach logs. The CLI writes that same private result and calls command_io.emit_failure exactly once. The regression proves the durable fence, retained candidate, one terminal report and absence of private input; no retry or new financial writer is introduced.",
    },
    (ANDROID + "data/repository/LedgerCalendarRepository.kt", "refresh"): {
        "sha256": "4d5a6d5e55461db80af5e4b4d0081d26e04c5587264f7a3da83b2c22ee08fc04",
        "owner": "existing sanitized TicketboxNetwork output and unchanged read Result",
        "test": "android/app/src/test/java/com/ticketbox/data/repository/LedgerCalendarRepositoryTest.kt::ruleSurvivesReopenAndOfflineWithoutCrossingLogicalBindings",
        "reason": "The calendar value now has one domain definition with the original JSON names; the redundant output copy is removed. Refresh still validates the exact ledger/revision/timezone under the same mutex, checks active binding before cache writes, propagates cancellation, logs through logNetworkWarning, and returns the original failure. The cache encoding and error owner are unchanged.",
    },
    (ANDROID + "viewmodel/FundsViewModel.kt", "runAction"): {
        "sha256": "f17605aa43a5316b882490fc49c3f35cd89b01ad14c80e2bfb582ade4ad10636",
        "owner": "existing UiText error projection and sanitized TicketboxNetwork Logcat",
        "test": "android/app/src/test/java/com/ticketbox/data/repository/NetworkErrorReportingTest.kt",
        "reason": "This UI boundary reports unexpected action failures through the existing sanitized sink; toUiText renders known local/domain failures or a generic message. The captured binding limits updates to the original session, finally releases busy state, and cancellation propagates. Funds input and its original Outbox command remain owned by FundsRepository. The referenced test qualifies the shared sink; retained-input and binding behavior additionally use the funds consumer journey.",
    },
    (ANDROID + "data/repository/FundsCommand.kt", "dispatch"): {
        "sha256": "d5f31740ddf189f1bba45fafb7868fc9d42c18de8c29152bd389d8f9b4db0c49",
        "owner": "existing NetworkErrorHandler and sanitized TicketboxNetwork Logcat",
        "test": "android/app/src/test/java/com/ticketbox/data/repository/NetworkErrorReportingTest.kt::fundsReplayFailureReportsSafelyWithoutRetryingOrConsumingTheCommand",
        "reason": "HTTP failures use NetworkErrorHandler. Unknown response failures report through logNetworkWarning and block the unchanged original command for review, without retrying or claiming acceptance. Cancellation propagates; transport interruption retains the existing retry owner. The existing failure-to-retry test verifies compact receipts and preserves the original payload/key across an unverified response. No financial inputs or raw exception messages are emitted.",
    },
    (ANDROID + "data/repository/NotificationCaptureDispatcher.kt", "dispatch"): {
        "sha256": "b1787d5f05ade2c64cc1ab2db812cd0162bf53ce148a24c28fcdb4dbbae8c099",
        "owner": "existing HTTP mapping, Outbox result and sanitized TicketboxNetwork output",
        "test": "android/app/src/test/java/com/ticketbox/data/repository/NotificationCaptureRepositoryTest.kt",
        "reason": "Cancellation propagates. Transport and binding changes retain the original; unexpected response or publication errors report through logNetworkWarning before retaining a failed original. NetworkErrorReportingTest verifies the shared sanitized sink. No raw notification or exception message is emitted.",
    },
    (ANDROID + "data/repository/PaymentCaptureResolution.kt", "dispatch"): {
        "sha256": "7a278106a9dbe5f4eb03a90deceaf0eb7dd1acd006d555b6e5f5eca799552709",
        "owner": "existing HTTP mapping, retained Outbox command and sanitized TicketboxNetwork output",
        "test": "android/app/src/androidTest/java/com/ticketbox/data/repository/NotificationCaptureRoomTest.kt",
        "reason": "An accepted correction whose projection fails remains retryable with its original key; cancellation propagates and unexpected failures use logNetworkWarning. HTTP rejections retain their existing mapper. NetworkErrorReportingTest verifies the reused sanitized sink; no retry here changes financial facts or allocates another intent.",
    },
    (ANDROID + "data/repository/RepaymentReviewDispatchers.kt", "dispatch"): {
        "sha256": "0b5bcf22e19496b1f7a4022d1b703d4473bafc7d9d40b2087a48ef0bdcac330c",
        "owner": "existing repayment delivery mapping, Outbox retry and sanitized TicketboxNetwork output",
        "test": "android/app/src/androidTest/java/com/ticketbox/data/repository/RepaymentReviewRoomTest.kt::rawInputAndOriginalReceiptSurviveReopenAndQueryCleanup",
        "reason": "Dispatch now reads the same admitted original wire payload directly, while UI receives a separate domain projection; the existing delivery and post-acceptance publication error policy is unchanged. The added catch is only after repayment acceptance and preserves the same command until source-expense projection succeeds. Cancellation propagates, failures report through logNetworkWarning, and no Done receipt is published early. NetworkErrorReportingTest verifies the reused sanitized sink.",
    },
    ("backend/app/services/integration_settings_service.py", "discover_local_models"): {
        "sha256": "ae7785abaf829801ef941f40e489fc964fef12a1b9e18c41d2255c9186f69af6",
        "owner": "existing HTTP exception handler and sanitized ticketbox.http output",
        "test": "backend/tests/test_owner_integration_settings.py::test_local_scan_worker_failures_reach_http_log",
        "reason": "The request consumes the pool.map iterator and joins the bounded pool before returning. Unexpected Future errors propagate to the HTTP boundary with the original traceback and request id; no detached job or new output owner exists. Expected unavailable model services produce an empty discovery result without changing settings.",
    },
    ("backend/app/services/background_task_executor.py", "_ExecutorPool._dispatch"): {
        "sha256": "948a9ef77b36a9e06dd4861658508212ca6242b5322ceff72ad25d8241f88f2a", "owner": "pool completion reports Future errors; inline errors propagate to submit_committed",
        "test": "backend/tests/test_background_task_claim.py::test_claim_failure_is_observed_without_publishing_a_new_task_state",
        "reason": "Dispatch reserves capacity only for durable PG rows. Its Future callback observes outside-handler errors through _finished and _report_worker_outcome; callback dispatch refusal is also reported without inventing task completion. The common owner checks require every link. The original queued row remains recoverable after refusal.",
    },
    ("backend/app/services/ocr_worker_client.py", "OcrWorkerClient._start"): {
        "sha256": "6753d04df3769d07f443366d42126fcf55e28dd76f7c2163e5ff2013aa830d57",
        "owner": "bounded pipe response consumed by the task runner; unexpected reader errors use the shared sanitized logger",
        "test": "backend/contract_tests/test_ocr_worker_process.py::test_unexpected_reader_failure_is_observed_and_owned_process_is_reaped",
        "reason": "The reader only transports one bounded response/error to recognize. Invalid IPC, exit and timeout retire the owned process tree before releasing capacity; unexpected reader exceptions report and wake the caller with a safe code. Idle retirement has its own shared reporting boundary and fences new work after cleanup failure. Attachment cleanup runs in finally, including interruption; test_attachment_failure_reaps_child_and_propagates_original_error verifies the child exits, both pipes close and the original error propagates. Detached Windows startup removes the unowned console helper without changing the private pipes or reporting owner; the delayed-attachment console test proves no console is attached.",
    },
    ("backend/app/error_reporting.py", "report_error"): {
        "sha256": "846d33fc9a0853f2617085a4fd235523e42239695788f98212c58c9b8fbcaa82", "owner": "final log sink failure stays outside business state",
        "test": "backend/tests/test_error_reporting_runtime.py::test_logging_sink_failure_does_not_replace_http_outcomes",
        "reason": "Only the log call is suppressed; there is no business retry, persistence or recursive reporting.",
    },
    (ANDROID + "data/repository/NetworkErrorHandler.kt", "safeCall"): {
        "sha256": "017fb0f6d8be62fc92089382d6c3ca0004a14207945950aa7cd9908b1017aac7", "owner": "public repository failure mapping and sanitized Logcat",
        "test": "android/app/src/test/java/com/ticketbox/data/repository/NetworkErrorReportingTest.kt",
        "reason": "Cancellation reraises and existing RepositoryException is returned; unexpected outcomes are logged before mapping.",
    },
    (ANDROID + "data/repository/NetworkErrorReporting.kt", "logNetworkWarning"): {
        "sha256": "58d8569c1a2ae044feb3eb78064704e73e79e9c6232a9ce11efd2d32f1881e40", "owner": "the existing TicketboxNetwork Logcat output",
        "test": "android/app/src/test/java/com/ticketbox/data/repository/NetworkErrorReportingTest.kt",
        "reason": "Sanitized message plus project frames, with no raw Throwable argument; an output failure cannot change the Result.",
    },
    (ANDROID + "data/repository/CreateDebtDispatcher.kt", "dispatch"): {
        "sha256": "115063a62d8963e1acdd03908784189a97df0eec3ab30041166327a98b25207d",
        "owner": "existing HTTP mapping and sanitized TicketboxNetwork output",
        "test": "android/app/src/test/java/com/ticketbox/data/repository/NetworkErrorReportingTest.kt::debtCreateFailureReportsSafelyWithoutSettlingTheOriginal",
        "reason": "Unexpected create replay failures report through logNetworkWarning before a blocking Failure retains the original payload and key. Receipt mismatches emit a static diagnostic. Cancellation propagates; transport retries keep their existing owner, and no raw exception text or unverified acceptance reaches the user.",
    },
    (ANDROID + "data/repository/DebtCreationRepository.kt", "createDebt"): {
        "sha256": "3d213c522598d6931abce01013202f6a7c5292df893b779d6ae90b3229b471b0",
        "owner": "existing sanitized TicketboxNetwork output and local acceptance Result",
        "test": "android/app/src/test/java/com/ticketbox/data/repository/NetworkErrorReportingTest.kt::debtLocalPublicationFailureReportsWithoutInventingAcceptance",
        "reason": "Unexpected storage or encoding errors report through logNetworkWarning before returning unverified local acceptance. Cancellation propagates and existing RepositoryException is preserved. No network call, new creation key, raw exception text or invented Debt receipt is introduced by the reporting boundary.",
    },
    (ANDROID + "ui/navigation/StatsRoutes.kt", "rememberDebtBillImageLauncher"): {
        "sha256": "4ef79b17f836f6bb070153ff4b187a113d0aed05cae1a9f208d8d3a58111f505",
        "owner": "existing sanitized TicketboxNetwork output and original preparation attempt",
        "test": "android/app/src/test/java/com/ticketbox/ui/navigation/DebtBillLauncherPreparationTest.kt",
        "reason": "A ContentResolver preparation fault reports a fixed operation label without provider messages, then settles only the original attempt through the existing binding/generation check. The real shared launcher tests preserve draft, selected bytes and lack of financial acceptance. Normal cancellation clears its own busy state, propagates and emits no diagnostic.",
    },
    (ANDROID + "viewmodel/DebtCreationDraftStore.kt", "persistBillDraft"): {
        "sha256": "ce1a0cbd2c835008bde7d69375bd0aa49d83e5b4a395f83f370244d62b9de50a",
        "owner": "existing sanitized TicketboxNetwork output and FactInputNotSaved presentation",
        "test": "android/app/src/test/java/com/ticketbox/viewmodel/DebtBillDraftContinuityTest.kt::failedOriginalDraftWriteBlocksCreateAndRetryKeepsTheSameSourceBodyAndKey",
        "reason": "Unexpected draft encoding or Room-write faults report through logNetworkWarning and retain their cause in a classified RepositoryException. The UI resolves FactInputNotSaved instead of raw SQL, local paths or private exception text. A failed original write prevents Debt admission; retry preserves the source, body and creation key. Cancellation propagates without reporting.",
    },
    (ANDROID + "viewmodel/DebtListDraftActions.kt", "runDebtBillTask"): {
        "sha256": "ff91758a7098aabba7100f28d68a7ec6e5581e33244bca4886ed240b2472c717",
        "owner": "existing DebtBillRepository NetworkErrorHandler.safeCall and original Result",
        "test": "android/app/src/test/java/com/ticketbox/viewmodel/DebtBillDraftContinuityTest.kt::editsBeforeCaptureAdmissionSurviveAColdEditorAndResumeTheOriginalTask",
        "reason": "Every production source operation already returns the shared safeCall Result. This composition preserves that same failure without a second log or retry; its local absence diagnostic is sanitized by debtBillTaskFailure into a classified resource message. Cancellation propagates, and no failed refresh/parse/discard becomes an ended source or accepted Debt. The existing continuation test verifies handled failure identity and quiet cancellation through this real function.",
    },
    (ANDROID + "viewmodel/DebtListViewModel.kt", "billTask"): {
        "sha256": "4833f47f04606c19c92e753f9191689b01b230f5deaee7e99a67c203481918b3",
        "owner": "existing shared repository errors and sanitized local draft recovery output",
        "test": "android/app/src/test/java/com/ticketbox/viewmodel/DebtBillDraftContinuityTest.kt",
        "reason": "Already classified RepositoryException results and expected current-draft refusals retain their existing objects/text without duplicate diagnostics. Unexpected local draft decode/recovery faults use logNetworkWarning and a fixed recovery message; malformed private fields cannot enter UI or Logcat. The original source and creation payload survive retry, and binding/generation guards plus cancellation behavior remain unchanged.",
    },
    (ANDROID + "data/repository/RecurringQueryReader.kt", "read"): {
        "sha256": "3fc23c76b1cb3b718259f815af0ee814205430e6d62836aa44ddd71352c34840",
        "owner": "existing NetworkErrorHandler.safeCall and sanitized TicketboxNetwork output",
        "test": "android/app/src/test/java/com/ticketbox/data/repository/RecurringQueryReadTest.kt::storagePublicationFailureKeepsFreshGetButRefusalOrMalformedResponseNeverUsesOldCache",
        "reason": "The broad catch only selects authorized cached reads for transport unavailability. Other errors, cancellation and cache validation failures propagate to the enclosing safeCall; HTTP refusal uses httpFailure before revoking cached access. NetworkErrorReportingTest proves the existing sanitized sink. Alias publication adds no independent terminal owner, retry or user-facing raw exception.",
    },
    (ANDROID + "data/repository/MonthlyArrangementRepository.kt", "arrangementHistory"): {
        "sha256": "a6ae4fbbd609560e48c5e5b5999fee965302e141bd4593969d98dc86e5a5e752",
        "owner": "existing NetworkErrorHandler.safeCall and sanitized TicketboxNetwork output",
        "test": "android/app/src/androidTest/java/com/ticketbox/data/repository/MonthlyArrangementRoomContinuityTest.kt::malformedJsonAndTlsFailureCannotBecomeCachedSuccess",
        "reason": "History and receipt snapshots now share canonical values with the original JSON fields; redundant input/output copies are removed. The existing exact binding, HTTP refusal withdrawal, transport-only cache fallback, receipt-version merge and snapshot publication rules are unchanged. No failure becomes a successful empty list, refreshed intent or new timestamp; NetworkErrorHandler.safeCall remains the reporting owner.",
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
        "sha256": "f557594cc93cb70035bf86c417d4487fb734678399d0d2952fe5886d813c1395",
        "owner": "existing HTTP mapping and sanitized TicketboxNetwork Logcat",
        "test": "android/app/src/test/java/com/ticketbox/data/repository/NetworkErrorReportingTest.kt::confirmReplayFailureReportsSafelyAndKeepsItsOriginalCommand",
        "reason": "Funding rejection maps to a retained conflict; unexpected errors still report through logNetworkWarning and preserve the original command, key and OCC. Cancellation propagates. The existing shared HTTP mapper owns request IDs and transport retries.",
    },
    (ANDROID + "data/repository/ConfirmRecurringCandidateDispatcher.kt", "dispatch"): {
        "sha256": "16eda617eeb4e0d0e924aace3aeec3c90c6da3dab54bca6f7e60f8157e2be7bb",
        "owner": "existing HTTP mapping and sanitized TicketboxNetwork output",
        "test": "android/app/src/test/java/com/ticketbox/data/repository/NetworkErrorReportingTest.kt::candidateReplayFailureReportsSafelyAndKeepsItsOriginalCommand",
        "reason": "Unexpected adoption replay failures report through logNetworkWarning while Outbox retains the original payload and key as unresolved. Receipt mismatches use a static diagnostic. No raw exception text reaches the UI; cancellation propagates and existing transport retry behavior is unchanged.",
    },
    (ANDROID + "data/repository/ApplyConfirmedRulesDispatcher.kt", "dispatch"): {
        "sha256": "3744f9c657235963732ddb0e42d4232db6b4ed13d2c373758d63a8e8b2281703",
        "owner": "NetworkErrorHandler for read/HTTP errors; sanitized TicketboxNetwork output for unexpected replay failures",
        "test": "android/app/src/test/java/com/ticketbox/data/repository/RuleApplicationCommandTest.kt",
        "reason": "The immutable application reason is now copied into the original request; it is not logged. A verified first receipt survives a later read failure or cancellation with a retained read-recovery flag. Repository read failures already use NetworkErrorHandler; unexpected callback and replay faults use logNetworkWarning without raw messages, changing keys, retrying or claiming acceptance.",
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
    ("backend/app/routes/web_debt_actions.py", "_repayment_outcome"): {
        "sha256": "77058a478d2da8873406362f9680b5ed69d26e65b79368c4124b8930d3a716e4",
        "owner": "existing HTTP reporter, with original command failures retained across an unavailable detail read",
        "test": "backend/tests/test_web_accounting_time.py::test_repayment_detail_failure_keeps_original_receipt_and_reporting_owner",
        "reason": "A failed detail read never replaces the accepted command receipt or unresolved original. HTTP 5xx is reported once by middleware with the retained first failure. A server-side read failure after acceptance reports through the same sanitized sink while keeping the actual response status and receipt. Expected read refusals do not emit error reports, and sink failure cannot change the business outcome.",
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
