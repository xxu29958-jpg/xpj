package com.ticketbox.data.repository

import com.ticketbox.data.local.ExpenseDao
import com.ticketbox.data.local.ExpenseEntity
import com.ticketbox.data.local.ExpenseOffsetStreamEntity
import com.ticketbox.domain.model.ConfirmedStreamItem
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

@OptIn(ExperimentalCoroutinesApi::class)
class ConfirmedStreamObservationTest {
    @Test
    fun delayedRootNotificationCannotTurnACommittedRefundIntoAnOrphan() = runTest {
        val stored = FakeExpenseDao()
        val roots = MutableStateFlow<List<ExpenseEntity>>(emptyList())
        val offsets = MutableStateFlow<List<ExpenseOffsetStreamEntity>>(emptyList())
        val dao = object : ExpenseDao by stored {
            override fun observeConfirmed(ledgerId: String) = roots
            override fun observeConfirmedStreamOffsets(ledgerId: String) = offsets
        }
        val repository = observedRepository(dao)
        var failure: Throwable? = null
        var visible = emptyList<ConfirmedStreamItem>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) {
            repository.observeConfirmedStream()
                .catch { failure = it }
                .collect { visible = it }
        }
        runCurrent()

        val root = cachedConfirmedEntity(9, "root-9", "MUJI").copy(
            streamDate = "2026-08-29",
            streamSortTime = "2026-08-29T09:00:00Z",
            streamSortId = 9,
            streamAmountCents = 1200,
            lineageStatus = "partially_refunded",
            lineageHomeNetCents = 900,
        )
        val refund = observedRefund()
        // A completed database transaction contains both rows. Its independent
        // query flows are allowed to notify at different times.
        stored.insert(root)
        stored.upsertConfirmedStreamOffsets(listOf(refund))
        offsets.value = listOf(refund)
        runCurrent()

        assertNull(failure, "A delayed root notification must not crash the ledger")
        assertEquals(2, visible.size)
        assertEquals("MUJI", visible.filterIsInstance<ConfirmedStreamItem.OffsetRow>().single().root.merchant)

        roots.value = listOf(root)
        runCurrent()
        // The inverse notification order during a cache replacement must also
        // observe the committed empty snapshot, not old offsets with new roots.
        stored.clearAllExpenseCachesForLedger("owner")
        roots.value = emptyList()
        runCurrent()

        assertNull(failure, "A delayed offset notification must not crash the ledger")
        assertEquals(emptyList(), visible)
    }
}

private fun observedRepository(dao: ExpenseDao): ExpenseRepository = ExpenseRepository(
    expenseDao = dao,
    binding = testServerSessionBinding(
        apiClient = FakeApiServiceFactory(FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0)),
        settingsStore = boundSettingsStore(),
        tokenStore = TestSessionFixture().apply { saveToken("session-token") },
    ),
    deviceNameProvider = { "Android Test Device" },
)

private fun observedRefund() = ExpenseOffsetStreamEntity(
    ledgerId = "owner",
    publicId = "refund-1",
    rootServerId = 9,
    kind = "refund",
    streamDate = "2026-08-30",
    streamSortTime = "2026-08-30T09:00:00Z",
    streamSortId = 10,
    streamAmountCents = -300,
    amountCents = 300,
    originalAmountMinor = 300,
    originalCurrencyCode = "CNY",
    homeCurrencyCode = "CNY",
    category = "购物",
)
