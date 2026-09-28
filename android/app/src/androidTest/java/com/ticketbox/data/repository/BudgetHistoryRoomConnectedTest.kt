package com.ticketbox.data.repository

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.BudgetArrangementDto
import com.ticketbox.data.remote.dto.BudgetCategoryRequestDto
import com.ticketbox.data.remote.dto.BudgetHistoryDto
import com.ticketbox.data.remote.dto.BudgetRevisionDto
import com.ticketbox.data.remote.dto.BudgetMonthlyDto
import com.ticketbox.data.remote.dto.BudgetMonthlyUpdateRequestDto
import com.ticketbox.domain.model.BudgetMonthlyUpdate
import com.ticketbox.ui.navigation.OfflineBudgetTransport
import com.ticketbox.ui.navigation.offlineBudget
import java.net.ConnectException
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import retrofit2.HttpException
import retrofit2.Response

/** Budget history uses the real graph and disk Room, with only HTTP controlled. */
@RunWith(AndroidJUnit4::class)
class BudgetHistoryRoomConnectedTest {
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val transport = BudgetHistoryTransport()
    private val fixture = ExpenseCorrectionConnectedFixture(context, transport::wrap)

    @After fun close() = fixture.close()

    @Test fun originalMonthAndReadPagesSurviveRoomReopenWithoutBorrowingUnreadPagesOrChangingIntent() = runBlocking {
        val graph = fixture.reopen()
        val binding = requireNotNull(graph.expenseRepository.captureDeferredLedgerBinding())
        val reader = graph.budgetRepository
        val first = reader.history(binding, "2026-09", null).getOrThrow()
        val older = reader.history(binding, "2026-09", 6).getOrThrow()
        reader.enqueueSave(binding, "2026-09", BudgetMonthlyUpdate("JPY", 7, 2400)).getOrThrow()
        val originalIntent = fixture.stored()
        assertEquals(1, originalIntent.size)
        transport.offline = true

        val reopened = fixture.reopen().budgetRepository
        val cached = reopened.history(binding, "2026-09", null)
        assertTrue("Already-read budget history must remain readable after disk Room reopens offline", cached.isSuccess)
        assertEquals(first.value, cached.getOrThrow().value)
        assertEquals(first.fetchedAt, cached.getOrThrow().fetchedAt)
        assertTrue(cached.getOrThrow().fromCache)
        val cachedOlder = reopened.history(binding, "2026-09", 6).getOrThrow()
        assertEquals(older.value, cachedOlder.value)
        assertEquals(older.fetchedAt, cachedOlder.fetchedAt)
        assertTrue(cachedOlder.fromCache)
        assertTrue("An unread page cannot borrow another page", reopened.history(binding, "2026-09", 4).isFailure)
        assertTrue("Another month cannot borrow September history", reopened.history(binding, "2026-10", null).isFailure)
        assertEquals(originalIntent, fixture.stored())
    }

    @Test fun historyReadRefusalWithdrawsTheSameBindingsBudgetQueryAcrossRoomReopen() = runBlocking {
        val graph = fixture.reopen()
        val binding = requireNotNull(graph.expenseRepository.captureDeferredLedgerBinding())
        val reader = graph.budgetRepository
        reader.monthlyBudget("2026-09").getOrThrow()
        reader.history(binding, "2026-09", null).getOrThrow()
        val originalIntent = fixture.stored()
        transport.historyStatus = 403
        val refusal = reader.history(binding, "2026-09", null)
        assertEquals(403, (refusal.exceptionOrNull() as? RepositoryException)?.httpStatusCode)
        transport.historyStatus = null
        transport.offline = true
        transport.budget.offline = true

        assertTrue("History access refusal must also withdraw the retained budget query",
            reader.monthlyBudget("2026-09").isFailure)
        val reopened = fixture.reopen().budgetRepository
        assertTrue(reopened.monthlyBudget("2026-09").isFailure)
        assertTrue(reopened.history(binding, "2026-09", null).isFailure)
        assertEquals(originalIntent, fixture.stored())
    }

    @Test fun acceptedSaveRetiresTheHistoryHeadWithoutErasingImmutableOlderPages() = runBlocking {
        val graph = fixture.reopen()
        val binding = requireNotNull(graph.expenseRepository.captureDeferredLedgerBinding())
        val reader = graph.budgetRepository
        reader.history(binding, "2026-09", null).getOrThrow()
        val older = reader.history(binding, "2026-09", 6).getOrThrow()
        val started = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        transport.beforeRead = { started.complete(Unit); release.await() }
        val stale = async { reader.history(binding, "2026-09", null) }
        started.await()
        reader.enqueueSave(binding, "2026-09", BudgetMonthlyUpdate("JPY", 7, 2400)).getOrThrow()
        val original = fixture.stored().single()
        val api = object : ApiService by transport.budget.service {
            override suspend fun updateMonthlyBudget(month: String, request: BudgetMonthlyUpdateRequestDto,
                timezone: String?, idempotencyKey: String?): BudgetMonthlyDto {
                assertEquals(original["idempotencyKey"], idempotencyKey)
                assertEquals(BudgetMonthlyUpdateRequestDto("JPY", 7, 2400), request)
                return offlineBudget().copy(rowVersion = 8, totalAmountCents = 2400, flexBudgetCents = 2400,
                    remainingAmountCents = 1989, excludedCategories = emptyList(), categoryBudgets = emptyList())
            }
        }
        val adapters = OutboxAdapterGraph()
        val result = try {
            OutboxDrainEngine(fixture.outbox, listOf(SaveMonthlyBudgetDispatcher({ api }, adapters.budgetSaveAdapter,
                adapters.budgetReceiptAdapter, reader.invalidateBudgetReadsAfterDelivery)), now = fixture.clock::millis).drainOnce()
        } finally { release.complete(Unit) }
        assertEquals(1, result.done)
        assertTrue("A pre-save history reply cannot republish the retired history head", stale.await().isFailure)
        transport.offline = true
        val reopened = fixture.reopen().budgetRepository
        assertTrue(reopened.history(binding, "2026-09", null).isFailure)
        val retained = reopened.history(binding, "2026-09", 6).getOrThrow()
        assertEquals(older.value, retained.value)
        assertEquals(older.fetchedAt, retained.fetchedAt)
        assertTrue(retained.fromCache)
    }

    @Test fun competingReadsShareTheNewerConfirmedHistoryAndMalformedRepliesDoNotBecomeOfflineResults() = runBlocking {
        val graph = fixture.reopen()
        val binding = requireNotNull(graph.expenseRepository.captureDeferredLedgerBinding())
        val reader = graph.budgetRepository
        val started = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        transport.beforeRead = { started.complete(Unit); release.await() }
        val old = async { reader.history(binding, "2026-09", null) }
        started.await()
        transport.version = 8
        val current = try { reader.history(binding, "2026-09", null).getOrThrow() } finally { release.complete(Unit) }
        val delayed = old.await().getOrThrow()
        assertEquals(current.value, delayed.value)
        assertEquals(current.fetchedAt, delayed.fetchedAt)
        assertTrue(!delayed.fromCache)
        transport.wrongLedger = true
        assertTrue(reader.history(binding, "2026-09", null).isFailure)
        transport.offline = true
        val cached = fixture.reopen().budgetRepository.history(binding, "2026-09", null).getOrThrow()
        assertEquals(current.value, cached.value)
        assertEquals(current.fetchedAt, cached.fetchedAt)
        assertTrue(cached.fromCache)
        fixture.switchAccount()
        assertTrue(fixture.graph.budgetRepository.history(binding, "2026-09", null).isFailure)
        assertTrue(fixture.stored().isEmpty())
    }
}

internal class BudgetHistoryTransport {
    val budget = OfflineBudgetTransport()
    var offline = false
    var historyStatus: Int? = null
    var version = 7L
    var wrongLedger = false
    var beforeRead: (suspend () -> Unit)? = null

    fun wrap(delegate: ApiService): ApiService = object : ApiService by budget.wrap(delegate) {
        override suspend fun budgetHistory(month: String, beforeVersion: Long?): BudgetHistoryDto {
            historyStatus?.let { throw HttpException(Response.error<Any>(it, "{}".toResponseBody())) }
            if (offline) throw ConnectException("Synthetic unavailable history transport")
            val page = budgetHistoryPage(month, beforeVersion, version).let {
                if (wrongLedger) it.copy(ledgerId = "another-ledger") else it
            }
            beforeRead?.let { beforeRead = null; it() }
            return page
        }
    }
}

internal fun budgetHistoryPage(month: String = "2026-09", before: Long? = null, version: Long = 7) = BudgetHistoryDto(
    ledgerId = "correction-ledger", month = month,
    items = (if (before == null) listOf(version, version - 1) else listOf(before - 1)).map { revision ->
        BudgetRevisionDto(revision, "edit", "2026-09-01T00:00:00Z",
            BudgetArrangementDto("JPY", revision * 100, 50, -20, listOf("医疗"),
                listOf(BudgetCategoryRequestDto("餐饮", revision * 10)), archived = false))
    },
    nextBeforeVersion = if (before == null) version - 1 else null,
)
