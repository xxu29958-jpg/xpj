package com.ticketbox.data.repository

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.data.remote.dto.ExpenseAccountingTimeDto
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ExpenseTimeInput
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ExpenseAccountingTimeRoomTest {
    private val fixture = ExpenseCorrectionConnectedFixture(InstrumentationRegistry.getInstrumentation().targetContext)

    @After fun close() = fixture.close()

    @Test fun dateOnlyCreateRetainsOriginalTimeInputAndKeyAcrossRoomReopen() = runBlocking {
        val repository = fixture.reopen().expenseRepository
        val selected = ExpenseTimeInput("date_only", 3, "2026-05-01")
        val draft = ExpenseDraft(amountCents = 100, originalCurrencyCode = CurrencyCode.CNY,
            originalAmountMinor = 100, merchant = "Original", category = "其他", note = null,
            expenseTime = null, tags = null, valueScore = null, regretScore = null,
            ledgerHomeCurrency = CurrencyCode.CNY, timeInput = selected)
        val created = repository.createManualExpense(draft).getOrThrow()
        val clientRef = requireNotNull(created.clientRef)
        val original = fixture.stored().single()
        val before = requireNotNull(fixture.expenseDao.localRowIdForClientRef("correction-ledger", clientRef))
        fixture.reopen()
        assertEquals(original, fixture.stored().single())
        assertEquals(before, fixture.expenseDao.localRowIdForClientRef("correction-ledger", clientRef))
        val cached = fixture.expenseDao.getConfirmed("correction-ledger").single().toDomain()
        assertNull(cached.expenseTime)
        assertEquals("date_only", cached.accountingTime?.precision)
        assertEquals(selected.userLocalDate, cached.accountingTime?.userLocalDate)
        assertEquals(selected.calendarRevision, cached.accountingTime?.calendarRevision)
    }

    @Test fun singleBulkAndCreateReceiptPublicationPreserveOnlySameVersionEvidence() = runBlocking {
        fixture.reopen()
        val old = fixture.network.current
        val time = ExpenseAccountingTimeDto("unknown", accountingDate = "2026-05-01", calendarRevision = 1,
            basis = "legacy_expense_time")
        val adopted = old.copy(accountingTime = time).toEntity("correction-ledger")
        for (path in listOf("single", "bulk", "create")) {
            fixture.expenseDao.clearForLedger("correction-ledger")
            fixture.expenseDao.insert(adopted)
            val receipt = old.toEntity("correction-ledger")
            when (path) {
                "single" -> fixture.expenseDao.applyServerExpense("correction-ledger", receipt)
                "bulk" -> fixture.expenseDao.upsertAllByServerIdForLedger("correction-ledger", listOf(receipt))
                "create" -> fixture.expenseDao.applyLocalCreateServerIdentity("correction-ledger", receipt.copy(clientRef = "original-ref"))
            }
            fixture.reopen()
            assertEquals(time.toDomain(), fixture.expenseDao.findByServerId("correction-ledger", old.id)?.toDomain()?.accountingTime)
            fixture.expenseDao.applyServerExpense("correction-ledger", old.copy(rowVersion = old.rowVersion + 1).toEntity("correction-ledger"))
            assertNull(fixture.expenseDao.findByServerId("correction-ledger", old.id)?.toDomain()?.accountingTime)
        }
    }
}
