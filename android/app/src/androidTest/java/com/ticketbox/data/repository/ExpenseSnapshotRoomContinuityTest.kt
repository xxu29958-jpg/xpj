package com.ticketbox.data.repository

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.isEnabled
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onFirst
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.lifecycle.viewModelScope
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.ui.screens.settings.SyncStatusNavigation
import com.ticketbox.ui.screens.settings.SyncStatusScreen
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.OutboxRecoveryRepositories
import com.ticketbox.viewmodel.OutboxStatusViewModel
import com.ticketbox.viewmodel.outboxStatusViewModelFactory
import java.io.IOException
import java.time.Clock
import java.time.Duration
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Disk Room, real offline saves, dispatcher and Sync UI. Failure is injected at publication, not inside Room. */
class ExpenseSnapshotRoomContinuityTest {
    @get:Rule val compose = createComposeRule()
    @Volatile private lateinit var current: ExpenseDto
    private lateinit var originalSnapshot: ExpenseDto
    @Volatile private var offline = false
    @Volatile private var staleRead = false
    private val reads = AtomicInteger()
    private val attempts = AtomicInteger()
    private val commits = CopyOnWriteArrayList<Pair<ExpenseUpdateRequest, String>>()
    private lateinit var sendingApi: ApiService
    private var global: OutboxStatusViewModel? = null
    private val fixture = ExpenseCorrectionConnectedFixture(InstrumentationRegistry.getInstrumentation().targetContext) { api ->
        object : ApiService by api {
            override suspend fun expense(id: Long): ExpenseDto {
                reads.incrementAndGet()
                if (offline) throw IOException("Offline canonical expense read")
                check(id == current.id)
                return if (staleRead) originalSnapshot else current
            }

            override suspend fun updateExpense(id: String, request: ExpenseUpdateRequest, idempotencyKey: String?): ExpenseDto {
                attempts.incrementAndGet()
                if (offline) throw IOException("Offline before submission")
                check(id == current.id.toString() && request.expectedRowVersion == current.rowVersion)
                check(!idempotencyKey.isNullOrBlank())
                commits += request to idempotencyKey
                return current.copy(merchant = request.merchant, rowVersion = current.rowVersion + 1).also { current = it }
            }
        }.also { sendingApi = it }
    }

    @After fun close() {
        compose.runOnIdle { global?.viewModelScope?.cancel() }
        fixture.close()
    }

    @Test
    fun deliveredPatchesKeepKnownTokensAndVisibleRefreshUntilCanonicalReadAfterRoomReopen() = runBlocking {
        val repository = fixture.reopen().expenseRepository
        current = fixture.network.current.copy(status = "pending", confirmedAt = null)
        originalSnapshot = current
        val baseline = repository.fetchExpense(42).getOrThrow()
        offline = true
        assertTrue(repository.saveExpenseAllowingOffline(42, draft("First saved merchant"), baseline).getOrThrow() is SaveOutcome.Queued)
        assertTrue(repository.saveExpenseAllowingOffline(42, draft("Second saved merchant"), baseline).getOrThrow() is SaveOutcome.Queued)
        val originals = fixture.stored()
        assertEquals(2, originals.size)
        assertTrue(commits.isEmpty())
        offline = false

        assertEquals(2, drain().done)
        assertEquals(listOf(7L, 8L), commits.map { it.first.expectedRowVersion })
        assertEquals(originals.map { it["idempotencyKey"] }, commits.map { it.second })
        assertEquals(9L, current.rowVersion)
        assertEquals(7L, repository.fetchExpenseFromLocalCache(42).getOrThrow().rowVersion)
        val delivered = fixture.stored()
        assertOriginalFields(originals, delivered)
        assertEquals(listOf("7", "8"), delivered.map { it["expectedRowVersion"] })
        assertRefreshRequired(delivered)
        val acceptedAttempts = attempts.get()
        assertEquals(0, drain().attempted)
        assertEquals(acceptedAttempts, attempts.get())

        val reopened = fixture.reopen().expenseRepository
        assertEquals(delivered, fixture.stored())
        val binding = requireNotNull(fixture.outbox.observeStatus().first().binding)
        val cleanup = OutboxRepository(fixture.pendingDao, Clock.offset(fixture.clock, Duration.ofDays(14)),
            bindingProvider = { binding }, onRowsDeleted = {})
        assertEquals(0, cleanup.gcCompleted())
        assertEquals(delivered, fixture.stored())
        showSync()
        compose.waitUntil(10_000) { compose.onAllNodes(hasText(REFRESH_REQUIRED)).fetchSemanticsNodes().isNotEmpty() }
        compose.onAllNodes(hasText(REFRESH_REQUIRED)).onFirst().performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("重试原提交").assertDoesNotExist()

        offline = true
        refreshAndAwaitRead()
        assertEquals(delivered, fixture.stored())
        offline = false
        staleRead = true
        refreshAndAwaitRead()
        assertEquals(delivered, fixture.stored())
        assertEquals(0, cleanup.gcCompleted())

        staleRead = false
        clickRefresh()
        compose.waitUntil(10_000) { fixture.stored().all { it["lastError"] == null } }
        compose.waitUntil(10_000) { compose.onAllNodes(hasText(REFRESH_REQUIRED)).fetchSemanticsNodes().isEmpty() }
        assertEquals(delivered.map { it + ("lastError" to null) }, fixture.stored())
        assertEquals(9L, reopened.fetchExpenseFromLocalCache(42).getOrThrow().rowVersion)
        assertEquals("Second saved merchant", reopened.getCachedPending().getOrThrow().single().merchant)
        assertEquals(0, drain().attempted)
        assertEquals(acceptedAttempts, attempts.get())
        assertEquals(2, commits.size)
        assertEquals(2, cleanup.gcCompleted())
    }

    private suspend fun drain() = OutboxDrainEngine(fixture.outbox, listOf(PatchExpenseDispatcher(
        apiProvider = { sendingApi }, payloadAdapter = OutboxAdapterGraph().patchExpenseAdapter,
        publishExpense = { _, _ -> throw IOException("Synthetic snapshot publication failure after accepted response") },
    )), now = fixture.clock::millis).drainOnce()

    private fun showSync() {
        val graph = fixture.graph
        compose.runOnIdle {
            global = outboxStatusViewModelFactory(fixture.outbox, graph.expenseRepository,
                OutboxRecoveryRepositories(graph.debtCreationRepository, graph.recurringRepository.occurrences,
                    graph.incomePlanRepository, graph.debtWriteRepository, graph.goalEditRepository, graph.budgetRepository,
                    graph.recurringRepository, graph.ruleRepository)).create(OutboxStatusViewModel::class.java)
        }
        compose.setContent { TicketboxTheme(skin = AppSkin.Paper) {
            SyncStatusScreen(requireNotNull(global), {}, SyncStatusNavigation({}, {}, {}, {}, {}, {}, {}, {}, {},
                onRepairCorrectionRate = { _, _ -> }))
        } }
        compose.waitUntil(10_000) { global?.uiState?.value?.bindingReady == true }
    }

    private fun clickRefresh() = compose.onAllNodes(hasText("刷新账单")).onFirst().performScrollTo().performClick()

    private fun refreshAndAwaitRead() {
        val before = reads.get()
        clickRefresh()
        compose.waitUntil(10_000) { reads.get() > before &&
            compose.onAllNodes(hasText("刷新账单") and isEnabled()).fetchSemanticsNodes().isNotEmpty() }
    }

    private fun assertOriginalFields(before: List<Map<String, String?>>, after: List<Map<String, String?>>) {
        for (column in listOf("payload", "idempotencyKey", "ownerKey", "ledgerId", "targetId", "createdAt")) {
            assertEquals(column, before.map { it[column] }, after.map { it[column] })
        }
    }

    private fun assertRefreshRequired(rows: List<Map<String, String?>>) {
        assertTrue(rows.all { it["status"] == "done" })
        assertTrue(rows.all { !it["lastError"].isNullOrBlank() })
    }

    private fun draft(merchant: String) = ExpenseDraft(amountCents = 1000, originalCurrencyCode = CurrencyCode.CNY,
        originalAmountMinor = 1000, ledgerHomeCurrency = CurrencyCode.CNY, merchant = merchant, category = "Other",
        note = null, expenseTime = "2026-09-06T00:00:00Z", tags = null, valueScore = null, regretScore = null)

    private companion object {
        const val REFRESH_REQUIRED = "操作已完成，账单显示尚待更新。"
    }
}
