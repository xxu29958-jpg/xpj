package com.ticketbox.data.repository

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class OutboxHttpErrorTest {
    @Test
    fun unfulfilledDomainAndUnknownRefusalsRemainVisible() {
        listOf("expense_reversal_required", "items_sum_not_in_mismatch", "future_write_refusal").forEach { code ->
            val result = classify("""{ "error": "$code", "message": "请核对原提交。" }""")
            assertEquals(DispatchResult.Failure("请核对原提交。"), result)
        }
        assertTrue(classify("unrecognized response") is DispatchResult.Failure)
    }

    @Test
    fun errorCodeControlsRecoveryEvenWhenTheMessageMentionsAnotherError() {
        val body = """{"error":"future_write_refusal","message":"state_conflict / idempotency_key_in_progress"}"""
        assertTrue(classify(body) is DispatchResult.Failure)
        assertEquals(DispatchResult.Conflict("原内容已变化。"),
            classify("""{ "error": "state_conflict", "message": "原内容已变化。" }"""))
        assertTrue(classify("""{ "error": "idempotency_key_in_progress", "message": "等待结果。" }""")
            is DispatchResult.RetryableFailure)
    }

    private fun classify(body: String) = mapOutboxHttpException(HttpException(
        Response.error<Any>(409, body.toResponseBody("application/json".toMediaType())),
    ))
}
