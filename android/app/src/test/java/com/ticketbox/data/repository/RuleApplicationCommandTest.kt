package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.RuleApplyConfirmedRequestDto
import com.ticketbox.data.remote.dto.RuleApplyConfirmedResponseDto
import java.io.IOException
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class RuleApplicationCommandTest {
    @Test fun lostReplyRetainsFirstCommandThenAcceptedReadFailureOnlyRefreshes() = runTest {
        var readFails = true
        var reads = 0
        val f = CategoryRuleCommandFixture { reads++; if (readFails) throw IOException("Read unavailable") }
        val preview = f.repository.previewApplyConfirmedRules().getOrThrow()
        assertTrue(f.repository.confirmApplyConfirmedRules(f.binding.copy(ledgerId = "other"), preview).isFailure)
        f.repository.confirmApplyConfirmedRules(f.binding, preview).getOrThrow()
        val original = f.repository.observeApplications(f.binding).first().single().row
        assertTrue(f.repository.confirmApplyConfirmedRules(f.binding, preview).isFailure)
        val server = ApplyServer(f.api)
        val dispatcher = ApplyConfirmedRulesDispatcher({ server.api }, f.adapters.ruleApplicationAdapter,
            f.adapters.ruleApplicationReceiptAdapter) { f.repository.refreshAcceptedApplication(it).getOrThrow() }
        val engine = OutboxDrainEngine(f.outbox, listOf(dispatcher), maxAttempts = 1)
        assertEquals(0, server.keys.size)
        assertEquals(1, engine.drainOnce().failures)
        val failed = f.repository.observeApplications(f.binding).first().single()
        assertTrue(failed.canRetry)
        assertEquals(original.payloadJson, failed.row.payloadJson)
        assertEquals(original.idempotencyKey, failed.row.idempotencyKey)
        server.currentCategory = "医疗"
        server.loseReply = false
        f.repository.recoverApplication(f.binding, failed, false).getOrThrow()
        assertEquals(1, engine.drainOnce().done)
        val delivered = f.repository.observeApplications(f.binding).first().single()
        assertTrue(delivered.needsRefresh)
        assertFalse(delivered.canRetry)
        assertEquals(1, delivered.receipt?.changedCount)
        assertEquals(2, server.keys.size)
        assertEquals(1, server.keys.toSet().size)
        assertEquals("医疗", server.currentCategory)
        assertEquals(1, f.outbox.observeStatus().first().refreshRequired.size)
        readFails = false
        f.repository.recoverApplication(f.binding, delivered, false).getOrThrow()
        assertEquals(2, reads)
        assertEquals(2, server.keys.size)
        assertEquals(PendingMutationStatus.Done, f.repository.observeApplications(f.binding).first().single().row.status)
        assertTrue(f.outbox.observeStatus().first().refreshRequired.isEmpty())
    }

    @Test fun stalePreviewIsRetainedForReviewAndNeverRebasedUnderTheSameKey() = runTest {
        val f = CategoryRuleCommandFixture()
        val preview = f.repository.previewApplyConfirmedRules().getOrThrow()
        f.repository.confirmApplyConfirmedRules(f.binding, preview).getOrThrow()
        val original = f.repository.observeApplications(f.binding).first().single()
        val api = object : ApiService by f.api {
            override suspend fun applyConfirmedRules(request: RuleApplyConfirmedRequestDto, limit: Int,
                maxScan: Int, idempotencyKey: String?): RuleApplyConfirmedResponseDto = throw HttpException(retrofit2.Response.error<Any>(409,
                    """{"error":"preview_stale","message":"Preview changed"}""".toResponseBody("application/json".toMediaType())))
        }
        val dispatcher = ApplyConfirmedRulesDispatcher({ api }, f.adapters.ruleApplicationAdapter, f.adapters.ruleApplicationReceiptAdapter, {})
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
        OutboxDrainEngine(f.outbox, listOf(dispatcher)).drainOnce()
        val pending = f.repository.observeApplications(f.binding).first().single()
        assertFalse(pending.isDone)
        assertEquals(null, pending.receipt)
        assertEquals(original.row.idempotencyKey, pending.row.idempotencyKey)
        assertEquals(RULE_APPLICATION_UNVERIFIED, pending.row.lastError)
    }
}

private class ApplyServer(delegate: ApiService) {
    val keys = mutableListOf<String?>()
    private val receipts = mutableMapOf<String, RuleApplyConfirmedResponseDto>()
    var loseReply = true
    var currentCategory = "其他"
    val api = object : ApiService by delegate {
        override suspend fun applyConfirmedRules(request: RuleApplyConfirmedRequestDto, limit: Int, maxScan: Int,
            idempotencyKey: String?): RuleApplyConfirmedResponseDto {
            keys += idempotencyKey
            val receipt = receipts.getOrPut(requireNotNull(idempotencyKey)) {
                currentCategory = "餐饮"
                RuleApplyConfirmedResponseDto(false, 9, 1, commandKey = idempotencyKey,
                    applicationPublicId = "accepted-application", scanLimit = maxScan)
            }
            if (loseReply) throw IOException("Original reply lost")
            return receipt
        }
    }
}
