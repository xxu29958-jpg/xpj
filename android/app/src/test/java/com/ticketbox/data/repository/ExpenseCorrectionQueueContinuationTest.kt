package com.ticketbox.data.repository

import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseFactBundleDto
import com.ticketbox.data.remote.dto.ExpenseOffsetVoidRequestDto
import com.ticketbox.data.remote.dto.ExpenseLineageStatusDto
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import com.ticketbox.domain.model.ExpenseOffsetMutationOutcome
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.Parameterized
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
@RunWith(Parameterized::class)
internal class ExpenseCorrectionQueueContinuationTest(private val status: PendingMutationStatus) :
    ExpensePendingRepositoryOutboxTestBase() {
    @Test
    fun droppingTheCorrectionWakesAndDeliversTheOriginalQueuedOffsetVoid() = runTest {
        val queue = FakePendingMutationDao()
        val cache = FakeExpenseDao()
        var continuation: () -> Unit = {}
        val outbox = testOutboxRepository(queue, onEnqueued = { continuation() })
        val bundle = expenseFactBundleDtoFixture()
        val sent = mutableListOf<Pair<ExpenseOffsetVoidRequestDto, String>>()
        val api = object : ApiService by FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0) {
            override suspend fun expense(id: Long) = bundle.root.also { assertEquals(it.id, id) }
            override suspend fun voidExpenseOffset(
                id: String, offsetPublicId: String, request: ExpenseOffsetVoidRequestDto, idempotencyKey: String,
            ): ExpenseFactBundleDto {
                assertEquals(bundle.root.id.toString(), id)
                assertEquals(bundle.activeOffsets.single().publicId, offsetPublicId)
                sent += request to idempotencyKey
                return bundle.copy(activeOffsets = emptyList(), financialSummary = bundle.financialSummary.copy(
                    activeRefundedOriginalMinor = 0, remainingRefundableOriginalMinor = 1_200,
                    lineageHomeNetCents = 1_200, status = ExpenseLineageStatusDto.Confirmed))
            }
        }
        val adapter = moshi().adapter(ExpenseOffsetVoidOutboxPayload::class.java)
        val repository = repository(api, cache, outbox)
        val binding = requireNotNull(repository.observeCorrections().first().access).binding
        val correction = repository.submitCorrection(binding, bundle.root.toDomain(),
            ExpenseCorrectionDraft("Correct the merchant", merchant = "Original correction")).getOrThrow()
        if (status == PendingMutationStatus.Conflict) outbox.markConflict(correction, "Current fact changed")
        else outbox.markFailed(correction, "Uncertain original result")
        assertIs<ExpenseOffsetMutationOutcome.Queued>(repository.voidExpenseOffsetAllowingOffline(
            bundle.root.toDomain(), bundle.toDomain().activeOffsets.single(), "Undo the original refund").getOrThrow())
        val original = queue.rows.values.single { it.type == PendingMutationType.VoidExpenseOffset.wireValue }
        val engine = OutboxDrainEngine(outbox, listOf(VoidExpenseOffsetDispatcher({ api }, adapter) { ledgerId, response ->
            val projection = response.toCacheProjection(ledgerId)
            cache.applyExpenseFactBundle(ledgerId, projection.root, projection.activeOffsets)
        }))
        assertEquals(DrainSummary.IDLE, engine.drainOnce())
        assertTrue(sent.isEmpty())
        var wakeups = 0
        continuation = { wakeups++; launch { engine.drainOnce() } }

        repository.recoverCorrection(binding, correction, drop = true).getOrThrow()
        advanceUntilIdle()

        assertEquals(1, wakeups, "Accepted Drop must resume the already queued successor")
        val delivered = queue.rows.values.single()
        assertNotNull(delivered.attemptedAt)
        assertNotNull(delivered.completedAt)
        assertEquals(original.copy(status = "done", retryCount = 1, attemptedAt = delivered.attemptedAt,
            completedAt = delivered.completedAt), delivered)
        val payload = requireNotNull(adapter.fromJson(original.payload))
        assertEquals(listOf(ExpenseOffsetVoidRequestDto(payload.voidReason, original.expectedRowVersion) to
            requireNotNull(original.idempotencyKey)), sent)
        assertTrue(repository.recoverCorrection(binding, correction, drop = true).isFailure)
        assertEquals(1, wakeups, "A stale repeated Drop must not enqueue more work")
    }

    private fun repository(api: ApiService, cache: FakeExpenseDao, outbox: OutboxRepository): ExpenseRepository {
        val adapters = OutboxAdapterGraph()
        return ExpenseRepository(cache, testServerSessionBinding(TestApiServiceFactory(api), seededSettingsStore(),
            seededTokenStore()), offlineMutations = ExpenseOfflineMutationWiring(outbox = outbox,
            offsetVoidAdapter = moshi().adapter(ExpenseOffsetVoidOutboxPayload::class.java),
            correctionAdapter = adapters.correctionAdapter, billSplitReceiptAdapter = adapters.billSplitReceiptAdapter,
            billSplitCreateAdapter = adapters.billSplitCreateAdapter,
            legacyCorrectionAdapter = adapters.legacyCorrectionAdapter,
                manualCreateAdapter = com.ticketbox.OutboxAdapterGraph().manualCreateAdapter,
            ))
    }

    companion object {
        @JvmStatic
        @Parameterized.Parameters(name = "{0}")
        fun states() = listOf(PendingMutationStatus.Failed, PendingMutationStatus.Conflict)
    }
}
