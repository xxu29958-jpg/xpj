package com.ticketbox.data.repository

import retrofit2.HttpException

private val outboxHttpErrors = NetworkErrorHandler(serverUrlProvider = { null }, context = "Outbox")
private val outboxRecoveryErrorCodes = setOf(
    "runtime_version_mismatch", "client_upgrade_required", "rule_category_deleted", DEBT_ADJUSTMENT_NEGATIVE_REMAINING,
    BUDGET_CURRENCY_CONFLICT, DEBT_VOID_ORIGINAL_REQUIRES_REVIEW, DEBT_KIND_ORIGINAL_REQUIRES_REVIEW,
    EXPENSE_REJECTION_ORIGINAL_REQUIRES_REVIEW, EXPENSE_CONFIRMATION_ORIGINAL_REQUIRES_REVIEW,
    "split_total_exceeds_parent", "split_amount_exceeds_parent",
)

/** Persist known recovery reasons so the sync UI can explain the required next step. */
internal fun NetworkErrorHandler.ParsedError.outboxFailureMessage(): String =
    errorCode?.takeIf { it in outboxRecoveryErrorCodes } ?: message

/** An HTTP refusal needs positive domain evidence before it can retire an original command. */
internal fun mapOutboxHttpException(error: HttpException): DispatchResult {
    val parsed = outboxHttpErrors.parseHttpError(error)
    return mapOutboxHttpError(error.code(), parsed)
}

/** A missing Debt withdraws that query, while its original command remains available for review. */
internal fun mapDebtWriteHttpException(error: HttpException, publicId: String): DispatchResult {
    val parsed = outboxHttpErrors.parseHttpError(error)
    return when (val result = mapOutboxHttpError(error.code(), parsed)) {
        is DispatchResult.Discarded -> DispatchResult.Failure(result.reason, definitelyRejected = true,
            missingDebtPublicId = publicId.takeIf { error.code() == 404 && parsed.errorCode == "debt_not_found" })
        else -> result
    }
}

internal fun mapOutboxHttpError(statusCode: Int, parsed: NetworkErrorHandler.ParsedError): DispatchResult {
    val message = parsed.message
    return when (statusCode) {
        409 -> when (parsed.errorCode) {
            "state_conflict" -> DispatchResult.Conflict(message)
            BUDGET_CURRENCY_CONFLICT -> DispatchResult.Conflict(BUDGET_CURRENCY_CONFLICT)
            "idempotency_key_in_progress" -> DispatchResult.RetryableFailure(message)
            // Unknown and domain refusals do not prove this command was fulfilled.
            else -> DispatchResult.Failure(parsed.outboxFailureMessage())
        }
        404 -> DispatchResult.Discarded(message)
        408, 429, in 500..599 -> DispatchResult.RetryableFailure(message)
        else -> DispatchResult.Failure(parsed.outboxFailureMessage(), definitelyRejected = statusCode in setOf(400, 401, 403, 405, 410, 412, 422),
            credentialRejected = statusCode == 401)
    }
}
