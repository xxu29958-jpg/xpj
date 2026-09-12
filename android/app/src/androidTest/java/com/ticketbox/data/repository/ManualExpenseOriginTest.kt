package com.ticketbox.data.repository

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseDraft
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** The navigation's original identity is exercised through disk Room and the production repository. */
class ManualExpenseOriginTest {
    @Test fun originalAcceptanceSurvivesReopenAndDisposableExpenseCacheWithoutAnotherCommand() = runBlocking {
        val fixture = ExpenseCorrectionConnectedFixture(ApplicationProvider.getApplicationContext<Context>())
        try {
            val repository = fixture.reopen().expenseRepository
            val binding = requireNotNull(repository.captureDeferredLedgerBinding())
            repository.createManualExpense(paymentDraft(), binding, "original-payment").getOrThrow()
            val original = fixture.stored().single()
            val row = fixture.pendingDao.allRows().single()
            assertEquals(PendingMutationType.CreateExpense.wireValue, row.type)
            val request = requireNotNull(OutboxAdapterGraph().manualCreateAdapter.fromJson(row.payload))
            assertEquals("original-payment", request.clientRef)
            assertEquals("JPY", request.originalCurrency)
            assertEquals("1200", request.originalAmount)
            assertEquals("CNY", request.homeCurrencyCode)
            assertEquals(0L, row.expectedRowVersion)
            fixture.expenseDao.getConfirmed(binding.ledgerId).forEach { fixture.expenseDao.deleteByLocalId(it.id) }
            val reopened = fixture.reopen().expenseRepository
            assertTrue(reopened.hasManualExpense(binding, "original-payment").getOrThrow())
            reopened.createManualExpense(paymentDraft().copy(originalAmountMinor = 9999), binding, "original-payment").getOrThrow()
            assertEquals(original, fixture.stored().single())
        } finally { fixture.close() }
    }

    @Test fun staleBindingAndReadOnlyEntryCannotPublishIntoTheNewLedger() = runBlocking {
        val fixture = ExpenseCorrectionConnectedFixture(ApplicationProvider.getApplicationContext<Context>())
        try {
            val repository = fixture.reopen().expenseRepository
            val binding = requireNotNull(repository.captureDeferredLedgerBinding())
            fixture.switchLedger()
            assertTrue(repository.createManualExpense(paymentDraft(), binding, "old-payment").isFailure)
            assertTrue(repository.hasManualExpense(binding, "old-payment").isFailure)
            assertTrue(fixture.stored().isEmpty())
            fixture.role("viewer")
            val current = requireNotNull(repository.captureDeferredLedgerBinding())
            assertTrue(repository.createManualExpense(paymentDraft(), current, "viewer-payment").isFailure)
            assertFalse(repository.hasManualExpense(current, "viewer-payment").getOrThrow())
            assertTrue(fixture.stored().isEmpty())
        } finally { fixture.close() }
    }

    private fun paymentDraft() = ExpenseDraft(amountCents = null, originalCurrencyCode = CurrencyCode.JPY,
        originalAmountMinor = 1200, merchant = "日元订阅", category = "购物", note = null,
        expenseTime = "2026-09-12T04:00:00Z", tags = null, valueScore = null, regretScore = null,
        ledgerHomeCurrency = CurrencyCode.CNY)
}
