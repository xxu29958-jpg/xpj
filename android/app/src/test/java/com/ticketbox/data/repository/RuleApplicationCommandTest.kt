package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.RuleApplyConfirmedRequestDto
import com.ticketbox.data.remote.dto.RuleApplyConfirmedResponseDto
import java.io.IOException
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowLog
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], manifest = Config.NONE)
class RuleApplicationCommandTest {
    @Test fun unexpectedApplicationFailureReportsWithoutSettlingOrReplacingOriginal() = runTest {
        ShadowLog.clear()
        val f = CategoryRuleCommandFixture()
        f.repository.confirmApplyConfirmedRules(f.binding, f.repository.previewApplyConfirmedRules().getOrThrow()).getOrThrow()
        val original = f.repository.observeApplications(f.binding).first().single().row
        var calls = 0
        val api = object : ApiService by f.api {
            override suspend fun applyConfirmedRules(request: RuleApplyConfirmedRequestDto, limit: Int, maxScan: Int,
                idempotencyKey: String?): RuleApplyConfirmedResponseDto {
                calls += 1
                throw IllegalStateException("password=application-secret", IOException("private financial text"))
            }
        }
        val writer = ApplyConfirmedRulesDispatcher({ api }, f.adapters.ruleApplicationAdapter, f.adapters.ruleApplicationReceiptAdapter, {})
        f.dao.runnableBatches += listOf(f.dao.rows.keys.single())
        assertEquals(1, OutboxDrainEngine(f.outbox, listOf(writer)).drainOnce().failures)
        val retained = f.repository.observeApplications(f.binding).first().single()
        assertEquals(original.payloadJson, retained.row.payloadJson)
        assertEquals(original.idempotencyKey, retained.row.idempotencyKey)
        assertEquals(1, calls)
        val logs = ShadowLog.getLogsForTag("TicketboxNetwork")
        assertEquals(1, logs.size)
        val output = logs.single().msg.orEmpty()
        assertTrue(output.contains("operation=ApplyConfirmedRules") && output.contains("ApplyConfirmedRulesDispatcher.kt:"))
        assertTrue(output.contains("source_tree_sha256="))
        assertFalse(output.contains("application-secret") || output.contains("private financial text"))
        assertTrue(logs.all { it.throwable == null })
    }

    @Test fun stalePreviewIsRetainedForReviewAndNeverRebasedUnderTheSameKey() = runTest {
        val f = CategoryRuleCommandFixture()
        val preview = f.repository.previewApplyConfirmedRules().getOrThrow()
        assertTrue(f.repository.confirmApplyConfirmedRules(f.binding.copy(ledgerId = "other"), preview).isFailure)
        f.repository.confirmApplyConfirmedRules(f.binding, preview).getOrThrow()
        assertTrue(f.repository.confirmApplyConfirmedRules(f.binding, preview).isFailure)
        val original = f.repository.observeApplications(f.binding).first().single()
        val api = object : ApiService by f.api {
            override suspend fun applyConfirmedRules(request: RuleApplyConfirmedRequestDto, limit: Int,
                maxScan: Int, idempotencyKey: String?): RuleApplyConfirmedResponseDto = throw HttpException(retrofit2.Response.error<Any>(409,
                    """{"error":"preview_stale","message":"Preview changed"}""".toResponseBody("application/json".toMediaType())))
        }
        val dispatcher = ApplyConfirmedRulesDispatcher({ api }, f.adapters.ruleApplicationAdapter, f.adapters.ruleApplicationReceiptAdapter, {})
        f.dao.runnableBatches += listOf(f.dao.rows.keys.single())
        OutboxDrainEngine(f.outbox, listOf(dispatcher)).drainOnce()
        val rejected = f.repository.observeApplications(f.binding).first().single()
        assertEquals("preview_stale", rejected.row.lastError)
        assertFalse(rejected.canRetry)
        assertEquals(original.row.payloadJson, rejected.row.payloadJson)
        assertTrue(f.repository.recoverApplication(f.binding, rejected, false).isFailure)
        f.repository.recoverApplication(f.binding, rejected, true).getOrThrow()
        f.repository.confirmApplyConfirmedRules(f.binding, preview.copy(previewToken = "explicit-fresh-preview")).getOrThrow()
        val next = f.repository.observeApplications(f.binding).first().single()
        assertTrue(next.row.idempotencyKey != original.row.idempotencyKey)
        assertEquals("explicit-fresh-preview", next.original?.previewToken)
    }

    @Test fun responseForAnotherKeyCannotSettleTheOriginalApplication() = runTest {
        val f = CategoryRuleCommandFixture()
        f.repository.confirmApplyConfirmedRules(f.binding, f.repository.previewApplyConfirmedRules().getOrThrow()).getOrThrow()
        val original = f.repository.observeApplications(f.binding).first().single()
        val api = object : ApiService by f.api {
            override suspend fun applyConfirmedRules(request: RuleApplyConfirmedRequestDto, limit: Int, maxScan: Int,
                idempotencyKey: String?): RuleApplyConfirmedResponseDto = f.api.applyConfirmedRules(request, limit, maxScan, "other-key")
        }
        val dispatcher = ApplyConfirmedRulesDispatcher({ api }, f.adapters.ruleApplicationAdapter, f.adapters.ruleApplicationReceiptAdapter, {})
        f.dao.runnableBatches += listOf(f.dao.rows.keys.single())
        OutboxDrainEngine(f.outbox, listOf(dispatcher)).drainOnce()
        val pending = f.repository.observeApplications(f.binding).first().single()
        assertFalse(pending.isDone)
        assertEquals(null, pending.receipt)
        assertEquals(original.row.idempotencyKey, pending.row.idempotencyKey)
        assertEquals(RULE_APPLICATION_UNVERIFIED, pending.row.lastError)
    }
}
