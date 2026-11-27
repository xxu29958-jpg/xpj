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
        assertEquals(DispatchResult.Failure(EXPENSE_SUBTASK_ORIGINAL_REQUIRES_REVIEW),
            classify("""{ "error": "expense_subtask_original_requires_review", "message": "核对原分项操作。" }"""))
    }

    @Test
    fun businessReferenceAndRoute404RefusalsStayVisibleFailures() {
        listOf(
            "member_not_found" to "成员不存在或已停用。",
            "task_not_found" to "后台任务不存在或已结束。",
            "fund_account_not_found" to "这个资金账户不存在或你没有访问权限。",
            "route_not_found" to "账本版本过旧，请重启电脑上的小票夹后再试。",
            "ledger_not_found" to "账本不存在或没有访问权限。",
            "future_ref_not_found" to "关联记录不存在。",
        ).forEach { (code, expectedMessage) ->
            val result = classify(404, """{ "error": "$code", "message": "$expectedMessage" }""")
            assertEquals(DispatchResult.Failure(expectedMessage, definitelyRejected = true), result)
        }
        for (unparsedBody in listOf("", "{}", "<html>404</html>", """{"detail":"Not Found"}""")) {
            val result = classify(404, unparsedBody)
            assertTrue(result is DispatchResult.Failure && result.definitelyRejected, "unparsed 404 must fail visibly: $result")
        }
        listOf(
            "not_found" to "账单不存在。",
            "expense_not_found" to "账单不存在。",
            "debt_not_found" to "这笔欠款不存在。",
            "goal_not_found" to "目标不存在。",
            "recurring_item_not_found" to "固定支出不存在。",
            "merchant_alias_not_found" to "商家别名不存在。",
            "rule_not_found" to "分类规则不存在。",
        ).forEach { (code, expectedMessage) ->
            assertEquals(
                DispatchResult.Failure(expectedMessage, definitelyRejected = true),
                classify(404, """{ "error": "$code", "message": "$expectedMessage" }"""),
            )
        }
    }

    private fun classify(body: String) = classify(409, body)

    private fun classify(statusCode: Int, body: String) = mapOutboxHttpException(httpError(statusCode, body))

    private fun httpError(statusCode: Int, body: String) = HttpException(
        Response.error<Any>(statusCode, body.toResponseBody("application/json".toMediaType())),
    )
}
