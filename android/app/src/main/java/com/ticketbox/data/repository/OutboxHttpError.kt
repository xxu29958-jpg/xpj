package com.ticketbox.data.repository

import retrofit2.HttpException

private val outboxHttpErrors = NetworkErrorHandler(serverUrlProvider = { null }, context = "Outbox")
private val outboxRecoveryErrorCodes = setOf(
    "runtime_version_mismatch", "client_upgrade_required", "rule_category_deleted", DEBT_ADJUSTMENT_NEGATIVE_REMAINING,
)

/** Persist known recovery reasons so the sync UI can explain the required next step. */
internal fun NetworkErrorHandler.ParsedError.outboxFailureMessage(): String =
    errorCode?.takeIf { it in outboxRecoveryErrorCodes } ?: message

/** An HTTP refusal needs positive domain evidence before it can retire an original command. */
internal fun mapOutboxHttpException(error: HttpException): DispatchResult {
    val parsed = outboxHttpErrors.parseHttpError(error)
    val message = parsed.message
    return when (error.code()) {
        409 -> when (parsed.errorCode) {
            "state_conflict" -> DispatchResult.Conflict(message)
            "idempotency_key_in_progress" -> DispatchResult.RetryableFailure(message)
            // Unknown and domain refusals do not prove this command was fulfilled.
            else -> DispatchResult.Failure(parsed.outboxFailureMessage())
        }
        404 -> DispatchResult.Discarded(message)
        408, 429, in 500..599 -> DispatchResult.RetryableFailure(message)
        else -> DispatchResult.Failure(parsed.outboxFailureMessage())
    }
}
