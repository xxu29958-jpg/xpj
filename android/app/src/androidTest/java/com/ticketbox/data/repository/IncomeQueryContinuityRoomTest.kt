package com.ticketbox.data.repository

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** A fresh repository graph must recover actual GETs from disk, not from original write receipts. */
class IncomeQueryContinuityRoomTest {
    private val fixture = IncomePlanConnectedFixture(ApplicationProvider.getApplicationContext<Context>())

    @After fun close() = fixture.close()

    @Test fun previouslyReadIncomeForecastSurvivesDatabaseCloseAndOfflineReopenWithoutInventingWrites() = runBlocking {
        val first = fixture.reopen().incomePlanRepository
        val binding = requireNotNull(first.observeActiveLedgerAccess().first()).binding
        val observed = first.listActive(binding).getOrThrow()
        assertEquals("2026-09", observed.month)
        assertEquals(10_000L, observed.expectedAmountCents)
        fixture.network.failReads = true
        val reopened = fixture.reopen().incomePlanRepository.listActive(binding)
        assertTrue("A known income forecast disappeared after an offline process-style reopen: ${reopened.exceptionOrNull()}", reopened.isSuccess)
        val retained = reopened.getOrThrow()
        assertEquals(observed.plans, retained.plans)
        assertEquals(observed.month, retained.month)
        assertEquals(observed.expectedAmountCents, retained.expectedAmountCents)
        assertTrue(fixture.stored().isEmpty())
        assertTrue(fixture.network.creationCalls.isEmpty() && fixture.network.calls.isEmpty())
    }

    @Test fun previouslyReadIncomeDefinitionsSurviveOfflineReopenWithoutConsultingCurrentPlanAsHistory() = runBlocking {
        val first = fixture.reopen().incomePlanRepository
        val binding = requireNotNull(first.observeActiveLedgerAccess().first()).binding
        val observed = first.history(binding, "income-1", null).getOrThrow()
        assertEquals("八月工资预测", observed.items.single().snapshot.label)
        fixture.network.current = fixture.network.current.copy(label = "现在的另一名称", amountCents = 99_999)
        fixture.network.failReads = true
        val reopened = fixture.reopen().incomePlanRepository.history(binding, "income-1", null)
        assertTrue("Read definitions disappeared after an offline reopen: ${reopened.exceptionOrNull()}", reopened.isSuccess)
        assertEquals(observed, reopened.getOrThrow())
        assertTrue(fixture.stored().isEmpty())
        assertTrue(fixture.network.creationCalls.isEmpty() && fixture.network.calls.isEmpty())
    }
}
