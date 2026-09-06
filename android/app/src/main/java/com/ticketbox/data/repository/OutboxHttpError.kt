package com.ticketbox.data.repository

import retrofit2.HttpException

private val outboxHttpErrors = NetworkErrorHandler(serverUrlProvider = { null }, context = "Outbox")

/** An HTTP refusal needs positive domain evidence before it can retire an original command. */
internal fun mapOutboxHttpException(error: HttpException): DispatchResult {
    val parsed = outboxHttpErrors.parseHttpError(error)
    val message = parsed.message
    return when (error.code()) {
        409 -> when (parsed.errorCode) {
            "state_conflict" -> DispatchResult.Conflict(message)
            "idempotency_key_in_progress" -> DispatchResult.RetryableFailure(message)
            "runtime_version_mismatch", "client_upgrade_required" -> DispatchResult.Failure(
                "客户端与服务器版本不匹配。原提交已保留，请更新为配套版本后重试。",
            )
            // Unknown and domain refusals do not prove this command was fulfilled.
            else -> DispatchResult.Failure(message)
        }
        404 -> DispatchResult.Discarded(message)
        408, 429, in 500..599 -> DispatchResult.RetryableFailure(message)
        else -> DispatchResult.Failure(message)
    }
}
