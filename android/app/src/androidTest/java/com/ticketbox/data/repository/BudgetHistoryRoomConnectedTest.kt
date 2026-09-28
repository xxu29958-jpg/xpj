package com.ticketbox.data.repository

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.BudgetArrangementDto
import com.ticketbox.data.remote.dto.BudgetCategoryRequestDto
import com.ticketbox.data.remote.dto.BudgetHistoryDto
import com.ticketbox.data.remote.dto.BudgetRevisionDto
import com.ticketbox.domain.model.BudgetMonthlyUpdate
import com.ticketbox.ui.navigation.OfflineBudgetTransport
import java.net.ConnectException
import kotlinx.coroutines.runBlocking
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
        assertEquals(first, cached.getOrThrow())
        assertEquals(older, reopened.history(binding, "2026-09", 6).getOrThrow())
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
}

internal class BudgetHistoryTransport {
    val budget = OfflineBudgetTransport()
    var offline = false
    var historyStatus: Int? = null

    fun wrap(delegate: ApiService): ApiService = object : ApiService by budget.wrap(delegate) {
        override suspend fun budgetHistory(month: String, beforeVersion: Long?): BudgetHistoryDto {
            historyStatus?.let { throw HttpException(Response.error<Any>(it, "{}".toResponseBody())) }
            if (offline) throw ConnectException("Synthetic unavailable history transport")
            return budgetHistoryPage(month, beforeVersion)
        }
    }
}

internal fun budgetHistoryPage(month: String = "2026-09", before: Long? = null) = BudgetHistoryDto(
    ledgerId = "correction-ledger", month = month,
    items = (if (before == null) listOf(7L, 6L) else listOf(before - 1)).map { revision ->
        BudgetRevisionDto(revision, "update", "2026-09-01T00:00:00Z",
            BudgetArrangementDto("JPY", revision * 100, 50, -20, listOf("医疗"),
                listOf(BudgetCategoryRequestDto("餐饮", revision * 10)), archived = false))
    },
    nextBeforeVersion = if (before == null) 6L else null,
)
