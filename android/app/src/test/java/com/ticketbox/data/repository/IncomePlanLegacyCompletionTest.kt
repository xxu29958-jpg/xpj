package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.IncomePlanDto
import com.ticketbox.domain.model.CurrencyCode
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class IncomePlanLegacyCompletionTest {
    @Test fun oldSuccessAndDiscarded404BothRequireReviewAndAnExplicitLocalStop() = runTest {
        // The old income dispatcher returned Success() without a receipt or mapped 404 to Discarded.
        // Both outcomes were persisted as Done, so neither is proof of the original accepted command.
        val old404 = mapOutboxHttpException(HttpException(Response.error<IncomePlanDto>(404,
            """{"error":"not_found","message":"Synthetic old missing plan"}""".toResponseBody())))
        assertTrue(old404 is DispatchResult.Discarded)
        for (legacyResult in listOf(DispatchResult.Success(), old404)) {
            val f = IncomeCreationFixture()
            val payload = """{"revision":1,"planPublicId":"income-created","originalLabel":"原工资","originalAmountCents":1000,"homeCurrencyCode":"JPY","originSessionGeneration":"${f.binding.sessionGeneration}","originBindingRevision":"${f.binding.bindingRevision}","request":{"intent_month":"2026-09","expected_row_version":0,"amount_cents":1200}}"""
            val id = f.outbox.enqueue(PendingMutationType.UpdateIncomePlan, "income_plan:income-created", payload, 1, "legacy-edit-key")
            val engine = OutboxDrainEngine(f.outbox, listOf(object : OutboxMutationDispatcher {
                override val type = PendingMutationType.UpdateIncomePlan
                override suspend fun dispatch(row: OutboxRow) = legacyResult
            }))
            engine.drainOnce()
            val pending = f.pending(id)
            assertEquals(PendingMutationStatus.Done, pending.row.status)
            assertTrue(pending.requiresReview)
            assertFalse(pending.isConfirmed)
            assertFalse(pending.canRetry)
            assertTrue(pending.canDrop)
            assertTrue(f.repository.recoverSubmission(f.binding, pending, false).isFailure)
            assertEquals(payload, f.pending(id).row.payloadJson)
            assertEquals("legacy-edit-key", f.pending(id).row.idempotencyKey)
            assertEquals(1L, f.pending(id).row.expectedRowVersion)
            // Reading the current canonical plan permits an explicit fresh edit; old intent is not replayed.
            f.repository.enqueueUpdate(f.binding, f.latest.toDomain(), IncomePlanPatch("2026-09", 1,
                amountCents = 1300), CurrencyCode.JPY).getOrThrow()
            assertEquals(payload, f.pending(id).row.payloadJson)
            assertTrue(f.repository.recoverSubmission(f.binding.copy(ledgerId = "foreign"), pending, true).isFailure)
            assertTrue(f.repository.recoverSubmission(f.binding, pending.copy(row = pending.row.copy(payloadJson = "{}")), true).isFailure)
            f.repository.recoverSubmission(f.binding, pending, true).getOrThrow()
            assertTrue(f.repository.observeSubmissions(f.binding).first().none { it.row.id == id })
            assertTrue(f.keys.isEmpty(), "Local stop must send no server command")
        }
    }

    @Test fun verifiedAcceptedReceiptIsNotAnUncertainRecordThatCanBeStopped() = runTest {
        val f = IncomeCreationFixture()
        val id = f.repository.create(f.binding, f.draft).getOrThrow()
        f.loseAck = false
        f.engine().drainOnce()
        val pending = f.pending(id)
        assertTrue(pending.isConfirmed)
        assertFalse(pending.requiresReview)
        assertFalse(pending.canDrop)
        assertTrue(f.repository.recoverSubmission(f.binding, pending, true).isFailure)
        assertEquals(pending, f.pending(id))
    }
}
