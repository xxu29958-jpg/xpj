package com.ticketbox.data.repository

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.ticketbox.RepositoryGraph
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.BudgetArrangementDto
import com.ticketbox.data.remote.dto.BudgetHistoryDto
import com.ticketbox.data.remote.dto.BudgetRevisionDto
import com.ticketbox.data.remote.dto.RecurringDefinitionDto
import com.ticketbox.data.remote.dto.RecurringHistoryPageDto
import com.ticketbox.data.remote.dto.RecurringItemDto
import com.ticketbox.data.remote.dto.RecurringItemListResponseDto
import com.ticketbox.data.remote.dto.RecurringRevisionDto
import com.ticketbox.data.remote.dto.RecycleBinItemDto
import com.ticketbox.data.remote.dto.RecycleBinListResponseDto
import com.ticketbox.data.remote.dto.RecycleBinRestoreRequestDto
import com.ticketbox.data.remote.dto.RecycleBinRestoreResponseDto
import com.ticketbox.domain.model.BudgetMonthlyUpdate
import com.ticketbox.ui.navigation.offlineBudget
import java.io.IOException
import java.net.ConnectException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.runBlocking
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import retrofit2.HttpException
import retrofit2.Response

/** Generic recycle-bin restores must reach the actual query owners and survive disk Room reopening. */
@RunWith(AndroidJUnit4::class)
class PlanningRecycleRecoveryRoomTest {
    private val transport = PlanningRecycleTransport()
    private val fixture = ExpenseCorrectionConnectedFixture(ApplicationProvider.getApplicationContext(), transport::wrap)

    @After fun close() = fixture.close()

    @Test fun acceptedBudgetRestoreRetiresLateUnconfiguredReadAndHistoryHead() = runBlocking { acceptedRestore("monthly_budget") }
    @Test fun acceptedRecurringRestoreRetiresLateArchivedReadAndHistoryHead() = runBlocking { acceptedRestore("recurring_item") }
    @Test fun unknownBudgetRestoreCannotResurrectArchivedReadsAfterRoomReopen() = runBlocking { unknownRestore("monthly_budget") }
    @Test fun unknownRecurringRestoreCannotResurrectArchivedReadsAfterRoomReopen() = runBlocking { unknownRestore("recurring_item") }

    private suspend fun acceptedRestore(kind: String) = coroutineScope {
        val graph = fixture.reopen()
        val binding = requireNotNull(graph.expenseRepository.captureDeferredLedgerBinding())
        reads(graph, binding, kind).forEach { it.getOrThrow() }
        graph.budgetRepository.enqueueSave(binding, "2026-09", BudgetMonthlyUpdate("JPY", 7, 2400)).getOrThrow()
        val originalIntent = fixture.stored()
        val item = graph.ledgerRepository.refreshRecycleBin().getOrThrow().items.single { it.kind == kind }
        val started = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        transport.beforeRead = { started.complete(Unit); release.await() }
        val late = async { primaryRead(graph, binding, kind) }
        started.await()
        try { graph.ledgerRepository.restoreRecycleBinItem(item).getOrThrow() } finally { release.complete(Unit) }
        assertTrue("A read started before generic $kind restore must not republish the archived state", late.await().isFailure)
        assertEquals(7, transport.restores.single().expectedRowVersion)
        transport.offline = true
        reads(fixture.reopen(), binding, kind).forEach {
            assertTrue("A restored $kind must not reopen using its pre-restore query", it.isFailure)
        }
        assertEquals(originalIntent, fixture.stored())
    }

    private suspend fun unknownRestore(kind: String) {
        val graph = fixture.reopen()
        val binding = requireNotNull(graph.expenseRepository.captureDeferredLedgerBinding())
        reads(graph, binding, kind).forEach { it.getOrThrow() }
        graph.budgetRepository.enqueueSave(binding, "2026-09", BudgetMonthlyUpdate("JPY", 7, 2400)).getOrThrow()
        val originalIntent = fixture.stored()
        val item = graph.ledgerRepository.refreshRecycleBin().getOrThrow().items.single { it.kind == kind }
        transport.loseRestoreReply = true
        assertTrue(graph.ledgerRepository.restoreRecycleBinItem(item).isFailure)
        transport.offline = true
        val reopened = fixture.reopen()
        reads(reopened, binding, kind).forEach {
            assertTrue("The unknown $kind restore may already be accepted; its old query cannot be shown after restart", it.isFailure)
        }
        transport.offline = false
        if (kind == "monthly_budget") {
            val current = reopened.budgetRepository.monthlyBudget(binding, "2026-09").getOrThrow()
            assertTrue(current.value.configured)
            assertEquals(8L, current.value.rowVersion)
        } else {
            val current = reopened.recurringRepository.items(binding, includeArchived = true).getOrThrow().value.single()
            assertEquals("active", current.status)
            assertEquals(8L, current.rowVersion)
        }
        val confirmed = reads(reopened, binding, kind).map { it.getOrThrow() }
        transport.offline = true
        val cached = reads(fixture.reopen(), binding, kind).map { it.getOrThrow() as ReadSnapshot<*> }
        assertEquals(confirmed.map { (it as ReadSnapshot<*>).value }, cached.map { it.value })
        assertTrue(cached.all { it.fromCache })
        assertEquals(originalIntent, fixture.stored())
        assertEquals(1, transport.restores.size)
    }

    @Test fun rejectedBudgetRestoreLeavesAlreadyReadFactsUsable() = runBlocking {
        val graph = fixture.reopen()
        val binding = requireNotNull(graph.expenseRepository.captureDeferredLedgerBinding())
        val before = reads(graph, binding, "monthly_budget").map { (it.getOrThrow() as ReadSnapshot<*>).value }
        val item = graph.ledgerRepository.refreshRecycleBin().getOrThrow().items.single { it.kind == "monthly_budget" }
        transport.restoreStatus = 409
        assertTrue(graph.ledgerRepository.restoreRecycleBinItem(item).isFailure)
        transport.offline = true
        val retained = reads(fixture.reopen(), binding, "monthly_budget").map { it.getOrThrow() as ReadSnapshot<*> }
        assertEquals(before, retained.map { it.value })
        assertTrue(retained.all { it.fromCache })
        assertTrue(fixture.stored().isEmpty())
    }

    private suspend fun reads(graph: RepositoryGraph, binding: LogicalSessionBinding, kind: String): List<Result<*>> =
        if (kind == "monthly_budget") listOf(primaryRead(graph, binding, kind),
            graph.budgetRepository.history(binding, "2026-09", null))
        else listOf(primaryRead(graph, binding, kind),
            graph.recurringRepository.history(binding, "recycled-series", null))

    private suspend fun primaryRead(graph: RepositoryGraph, binding: LogicalSessionBinding, kind: String): Result<*> =
        if (kind == "monthly_budget") graph.budgetRepository.monthlyBudget(binding, "2026-09")
        else graph.recurringRepository.items(binding, includeArchived = true)
}

private class PlanningRecycleTransport {
    var offline = false
    var loseRestoreReply = false
    var restoreStatus: Int? = null
    var beforeRead: (suspend () -> Unit)? = null
    private var budgetVersion = 7L
    private var seriesVersion = 7L
    val restores = mutableListOf<RecycleBinRestoreRequestDto>()
    private val timestamp = "2026-09-01T00:00:00Z"

    private suspend fun checkRead() {
        if (offline) throw ConnectException("Synthetic unavailable planning read")
        beforeRead?.let { beforeRead = null; it() }
    }

    fun wrap(delegate: ApiService): ApiService = object : ApiService by delegate {
        override suspend fun monthlyBudget(month: String, timezone: String?) =
            offlineBudget().copy(month = month, configured = budgetVersion > 7,
                rowVersion = budgetVersion.takeIf { it > 7 }).also { checkRead() }

        override suspend fun budgetHistory(month: String, beforeVersion: Long?): BudgetHistoryDto {
            if (offline) throw ConnectException("Synthetic unavailable budget history")
            return BudgetHistoryDto("correction-ledger", month, listOf(BudgetRevisionDto(budgetVersion,
                if (budgetVersion == 7L) "archive" else "restore", timestamp,
                BudgetArrangementDto("JPY", 1200, 0, 0, emptyList(), emptyList(), budgetVersion == 7L))), null)
        }

        override suspend fun recurringItems(status: String?, includeArchived: Boolean, month: String?, timezone: String?) =
            RecurringItemListResponseDto(listOf(RecurringItemDto("recycled-series", "correction-ledger", "原日元计划", "原日元计划",
                "monthly", 1200, 1200, 0, null, "2026-09-09", if (seriesVersion == 7L) "archived" else "active",
                null, "manual", createdAt = timestamp, updatedAt = timestamp, rowVersion = seriesVersion,
                pausedAt = null, archivedAt = timestamp.takeIf { seriesVersion == 7L }, homeCurrencyCode = "JPY")))
                .also { checkRead() }

        override suspend fun recurringHistory(publicId: String, limit: Int, beforeVersion: Long?): RecurringHistoryPageDto {
            if (offline) throw ConnectException("Synthetic unavailable recurring history")
            return RecurringHistoryPageDto("correction-ledger", publicId, listOf(RecurringRevisionDto(seriesVersion,
                if (seriesVersion == 7L) "archive" else "restore", timestamp, null,
                RecurringDefinitionDto("原日元计划", "原日元计划", "monthly", "JPY", 1200, "2026-09-09",
                    if (seriesVersion == 7L) "archived" else "active", "manual"))), null)
        }

        override suspend fun recycleBin() = RecycleBinListResponseDto(listOf(
            RecycleBinItemDto("monthly_budget", "月度预算", "2026-09", "九月预算", "已归档", retentionLabel = "可恢复", expectedRowVersion = 7),
            RecycleBinItemDto("recurring_item", "固定支出", "recycled-series", "原日元计划", "已归档", retentionLabel = "可恢复", expectedRowVersion = 7),
        ), 0)

        override suspend fun restoreRecycleBinItem(request: RecycleBinRestoreRequestDto): RecycleBinRestoreResponseDto {
            restores += request
            restoreStatus?.let { throw HttpException(Response.error<Any>(it, "{}".toResponseBody())) }
            when (request.kind) {
                "monthly_budget" -> budgetVersion++
                "recurring_item" -> seriesVersion++
                else -> error("Unexpected planning restore")
            }
            if (loseRestoreReply) throw IOException("Synthetic lost restore reply after acceptance")
            return RecycleBinRestoreResponseDto("已恢复")
        }
    }
}
