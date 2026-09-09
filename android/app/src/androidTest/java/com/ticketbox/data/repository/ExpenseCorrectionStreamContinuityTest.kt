package com.ticketbox.data.repository

import androidx.lifecycle.viewModelScope
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.data.remote.dto.ConfirmedExpenseStreamItemDto
import com.ticketbox.data.remote.dto.ConfirmedOffsetStreamDto
import com.ticketbox.data.remote.dto.ConfirmedStreamEntryKindDto
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseLineageStatusDto
import com.ticketbox.data.remote.dto.ExpenseOffsetKindDto
import com.ticketbox.domain.model.ConfirmedStreamItem
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import com.ticketbox.domain.model.ExpenseFilterCriteria
import com.ticketbox.domain.model.filterConfirmedStreamItems
import com.ticketbox.ui.screens.groupConfirmedStream
import com.ticketbox.viewmodel.LedgerUiState
import com.ticketbox.viewmodel.LedgerViewModel
import java.time.YearMonth
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.job
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Real Room, graph, sender and retained ledger; no detail reader or manual post-delivery sync. */
class ExpenseCorrectionStreamContinuityTest {
    @Test
    fun rejectedStreamPublicationKeepsTheDeliveredReceiptUntilAnAcceptedReadAfterReopen() = runBlocking {
        val fixture = ExpenseCorrectionConnectedFixture(InstrumentationRegistry.getInstrumentation().targetContext)
        try {
            var repository = fixture.reopen().expenseRepository
            fixture.network.loseResponse = false
            val originalExpense = fixture.network.current.copy(expenseTime = "2026-09-01T04:00:00Z")
            fixture.network.current = originalExpense
            fixture.network.confirmedStreamItems = { root -> rootStream(root,
                if (root.rowVersion == originalExpense.rowVersion) "2026-09-01" else "2026-10-02").let(::listOf) }
            repository.syncConfirmed().getOrThrow()
            val oldProjection = requireNotNull(fixture.expenseDao.findByServerId("correction-ledger", originalExpense.id))
            val access = requireNotNull(repository.observeCorrections().first().access)
            repository.submitCorrection(access.binding, originalExpense.toDomain(), ExpenseCorrectionDraft(
                reason = "Correct the date", expenseTime = "2026-10-02T04:00:00Z", expenseTimeChanged = true,
            )).getOrThrow()
            val original = fixture.stored().single()
            fixture.network.beforeStreamResponse = {
                fixture.network.current = fixture.network.current.copy(rowVersion = 9, merchant = "Concurrent newer fact")
                fixture.expenseDao.upsertByServerIdForLedger("correction-ledger", fixture.network.current.toEntity("correction-ledger"))
            }

            assertEquals(1, fixture.drain().done)
            val pending = repository.observeCorrections().first().corrections.single()
            assertTrue(pending.delivered)
            assertTrue("An incoming stream rejected by Room cannot satisfy the receipt", pending.refreshRequired)
            val raced = requireNotNull(fixture.expenseDao.findByServerId("correction-ledger", originalExpense.id))
            assertEquals(9L, raced.rowVersion)
            assertEquals(oldProjection.streamDate, raced.streamDate)
            assertEquals(oldProjection.streamAmountCents, raced.streamAmountCents)
            for (column in listOf("id", "payload", "idempotencyKey", "expectedRowVersion", "ownerKey", "ledgerId", "serverUrl")) {
                assertEquals("Original command $column", original[column], fixture.stored().single()[column])
            }
            fixture.network.beforeStreamResponse = null
            repository = fixture.reopen().expenseRepository
            assertTrue(repository.observeCorrections().first().corrections.single().refreshRequired)
            repository.syncConfirmed().getOrThrow()
            assertEquals(false, repository.observeCorrections().first().corrections.single().refreshRequired)
            assertEquals("2026-10-02", fixture.expenseDao.findByServerId("correction-ledger", originalExpense.id)?.streamDate)
            assertEquals(0, fixture.drain().attempted)
            assertEquals(1, fixture.network.calls.size)
        } finally {
            fixture.close()
        }
    }

    @Test
    fun deliveredAmountAndDateCorrectionUpdatesTheRetainedLedgerWithoutManualSync() = runBlocking {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val fixture = ExpenseCorrectionConnectedFixture(context)
        var owner: LedgerViewModel? = null
        try {
            val oldDate = YearMonth.now().atDay(1).toString()
            val newDate = YearMonth.parse(oldDate.take(7)).plusMonths(1).atDay(2).toString()
            val originalExpense = fixture.network.current.copy(expenseTime = "${oldDate}T04:00:00Z")
            fixture.network.current = originalExpense
            fixture.network.loseResponse = false
            val unaffected = untouchedRefundStream(originalExpense, oldDate)
            fixture.network.confirmedStreamItems = { current ->
                listOf(rootStream(current, if (current.rowVersion == originalExpense.rowVersion) oldDate else newDate)) + unaffected
            }
            val graph = fixture.reopen()
            val otherLedger = rootStream(originalExpense.copy(id = 501, publicId = "other-ledger-expense"), oldDate)
                .toConfirmedStreamCacheItem("untouched-ledger").root
            fixture.expenseDao.upsertByServerIdForLedger("untouched-ledger", otherLedger)
            val otherBefore = fixture.expenseDao.findByServerId("untouched-ledger", 501L)
            val ledger = withContext(Dispatchers.Main) { LedgerViewModel(graph.expenseRepository, graph.debtRepository) }
            owner = ledger
            val initial = withTimeoutOrNull(10_000) { ledger.uiState.first { !it.syncing && it.items.size == 3 } }
                ?: ledger.uiState.value
            assertTrue("Initial stream sync must complete: ${initial.message}", initial.syncedInCurrentSession)
            assertEquals(3, initial.items.size)
            assertEquals(mapOf("CNY" to 1_400L), initial.summary.amountsByCurrency)
            withContext(Dispatchers.Main) { ledger.clearFilters() }
            val repository = graph.expenseRepository
            val access = requireNotNull(repository.observeCorrections().first().access)
            repository.submitCorrection(access.binding, originalExpense.toDomain(), ExpenseCorrectionDraft(
                reason = "Correct the amount and accounting date", originalAmountMinor = 1_400,
                expenseTime = "${newDate}T04:00:00Z", expenseTimeChanged = true,
            )).getOrThrow()
            val original = fixture.stored().single()
            assertEquals(0, fixture.network.calls.size)
            assertEquals(1, fixture.drain().done)
            val delivered = repository.observeCorrections().first().corrections.single()
            assertTrue(delivered.delivered)
            val stored = fixture.stored().single()
            for (column in listOf("id", "payload", "idempotencyKey", "expectedRowVersion", "ownerKey", "ledgerId", "serverUrl")) {
                assertEquals("Original command $column", original[column], stored[column])
            }
            assertEquals(requireNotNull(delivered.intent).request to original["idempotencyKey"], fixture.network.calls.single())
            assertEquals(otherBefore, fixture.expenseDao.findByServerId("untouched-ledger", 501L))
            val published = awaitCorrectedStream(ledger, originalExpense.id, newDate)
            assertPublishedLedger(context.resources, published, originalExpense.id, oldDate, newDate)
            assertEquals(unaffected.map { it.toConfirmedStreamCacheItem("correction-ledger") }.mapNotNull { it.offset },
                fixture.expenseDao.getConfirmedStreamOffsets("correction-ledger"))
            assertEquals("Publishing the stream must not replay the correction", 1, fixture.network.calls.size)
        } finally {
            withContext(Dispatchers.Main) { owner?.viewModelScope?.coroutineContext?.job?.cancelAndJoin() }
            fixture.close()
        }
    }

    private suspend fun awaitCorrectedStream(ledger: LedgerViewModel, expenseId: Long, date: String): LedgerUiState =
        withTimeoutOrNull(10_000) {
            ledger.uiState.first { state -> state.items.any {
                it is ConfirmedStreamItem.ExpenseRow && it.root.id == expenseId &&
                    it.streamDate == date && it.streamAmountCents == 1_400L
            } }
        } ?: ledger.uiState.value

    private fun assertPublishedLedger(
        resources: android.content.res.Resources,
        state: LedgerUiState,
        expenseId: Long,
        oldDate: String,
        newDate: String,
    ) {
        val root = state.items.filterIsInstance<ConfirmedStreamItem.ExpenseRow>().single { it.root.id == expenseId }
        assertEquals(1_400L, root.root.amountCents)
        assertEquals("${newDate}T04:00:00Z", root.root.expenseTime)
        assertEquals("A delivered root must not retain its preceding stream date", newDate, root.streamDate)
        assertEquals(1_400L, root.streamAmountCents)
        assertEquals(mapOf("CNY" to 1_800L), state.summary.amountsByCurrency)
        val groups = groupConfirmedStream(resources, state.items)
        assertEquals(listOf(newDate, oldDate), groups.map { it.key })
        assertEquals(listOf(mapOf("CNY" to 1_400L), mapOf("CNY" to 400L)), groups.map { it.amountsByCurrency })
        val oldMonth = filterConfirmedStreamItems(state.items, ExpenseFilterCriteria(month = oldDate.take(7)))
        assertTrue(oldMonth.none { it.root.id == expenseId })
        val newMonth = filterConfirmedStreamItems(state.items, ExpenseFilterCriteria(month = newDate.take(7)))
        assertEquals(listOf(expenseId), newMonth.map { it.root.id })
    }

    private fun rootStream(root: ExpenseDto, date: String) = ConfirmedExpenseStreamItemDto(
        ConfirmedStreamEntryKindDto.Expense, date, requireNotNull(root.expenseTime), root.id,
        requireNotNull(root.amountCents), root, lineageStatus = ExpenseLineageStatusDto.Confirmed,
        lineageHomeNetCents = requireNotNull(root.amountCents),
    )

    private fun untouchedRefundStream(original: ExpenseDto, date: String): List<ConfirmedExpenseStreamItemDto> {
        val root = original.copy(id = 99, publicId = "untouched-expense", amountCents = 600, originalAmountMinor = 600)
        val bill = rootStream(root, date).copy(lineageStatus = ExpenseLineageStatusDto.PartiallyRefunded, lineageHomeNetCents = 400)
        return listOf(bill, bill.copy(entryKind = ConfirmedStreamEntryKindDto.Offset, streamSortId = 100,
            streamAmountCents = -200, offset = ConfirmedOffsetStreamDto("untouched-refund", ExpenseOffsetKindDto.Refund,
                200, 200, "CNY", "CNY", "餐饮")))
    }
}
