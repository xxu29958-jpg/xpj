package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.ExpenseDto
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.async
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.yield
import kotlin.test.Test
import kotlin.test.assertEquals

@OptIn(ExperimentalCoroutinesApi::class)
internal class ExpenseRepositoryPendingSyncTest {

    @Test
    fun cancelledOwnerDoesNotPoisonAttachedNewerSyncForTheLedger() = runTest {
        val coordinator = PendingSyncCoordinator()
        val requestStarted = CompletableDeferred<Unit>()
        val neverReturns = CompletableDeferred<Unit>()

        val owner = launch {
            coordinator.sync("owner") {
                requestStarted.complete(Unit)
                neverReturns.await()
                emptyList()
            }
        }
        requestStarted.await()
        val replacementOperationStarted = CompletableDeferred<Unit>()
        val replacement = async {
            coordinator.sync("owner") {
                replacementOperationStarted.complete(Unit)
                listOf(pendingExpense("识别后"))
            }
        }
        yield()
        owner.cancelAndJoin()

        val result = withTimeout(1_000) { replacement.await() }

        replacementOperationStarted.await()
        assertEquals("识别后", result.single().merchant)
    }

    @Test
    fun overlappingSameLedgerSyncsCoalesceAndLeaveNewestSnapshotInRoom() = runTest {
        val firstResponseCanReturn = CompletableDeferred<Unit>()
        val firstRequestStarted = CompletableDeferred<Unit>()
        var requestCount = 0
        val api = FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0).apply {
            onPendingRequest = {
                requestCount += 1
                if (requestCount == 1) {
                    firstRequestStarted.complete(Unit)
                    firstResponseCanReturn.await()
                    listOf(pendingDto(merchant = "识别前", rowVersion = 1L))
                } else {
                    listOf(pendingDto(merchant = "识别后", rowVersion = 2L))
                }
            }
        }
        val dao = FakeExpenseDao()
        val repository = ExpenseRepository(
            expenseDao = dao,
            binding = testServerSessionBinding(
                apiClient = FakeApiServiceFactory(api),
                settingsStore = boundSettingsStore(),
                tokenStore = TestSessionFixture().apply { saveToken("session-token") },
            ),
            deviceNameProvider = { "Android Test Device" },
        )

        val preEnrichment = async { repository.syncPending().getOrThrow() }
        firstRequestStarted.await()
        val terminal = async { repository.syncPending().getOrThrow() }
        yield()
        firstResponseCanReturn.complete(Unit)

        assertEquals("识别后", preEnrichment.await().single().merchant)
        assertEquals("识别后", terminal.await().single().merchant)
        assertEquals(2, requestCount)
        val cached = dao.getPending("owner").single()
        assertEquals("识别后", cached.merchant)
        assertEquals(2L, cached.rowVersion)
    }

    private fun pendingDto(merchant: String, rowVersion: Long): ExpenseDto = ExpenseDto(
        id = 42L,
        publicId = "pending-public-id",
        amountCents = 1234L,
        merchant = merchant,
        category = "餐饮",
        note = "",
        source = "Android截图",
        imagePath = "uploads/owner/receipt.png",
        thumbnailPath = null,
        imageHash = "hash",
        rawText = merchant,
        confidence = 0.9,
        duplicateStatus = "none",
        duplicateOfId = null,
        duplicateReason = null,
        tags = null,
        valueScore = null,
        regretScore = null,
        status = "pending",
        expenseTime = "2026-08-29T00:00:00Z",
        createdAt = "2026-08-29T00:00:00Z",
        updatedAt = "2026-08-29T00:00:01Z",
        rowVersion = rowVersion,
        confirmedAt = null,
        rejectedAt = null,
    )

    private fun pendingExpense(merchant: String) = pendingDto(merchant, rowVersion = 2L).toDomain()
}
