package com.ticketbox.ui.navigation

import android.Manifest
import android.app.NotificationManager
import android.content.Context
import android.os.Build
import androidx.lifecycle.ViewModelStore
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.NotificationRuntimeGraph
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.BudgetMonthlyUpdateRequestDto
import com.ticketbox.data.remote.dto.BudgetMonthlyDto
import com.ticketbox.data.repository.ExpenseCorrectionConnectedFixture
import com.ticketbox.data.repository.OutboxDrainEngine
import com.ticketbox.data.repository.SaveMonthlyBudgetDispatcher
import com.ticketbox.data.repository.newTaskMonth
import com.ticketbox.data.repository.toDomain
import com.ticketbox.domain.model.NotificationPreferences
import com.ticketbox.domain.model.BudgetMonthlyUpdate
import com.ticketbox.notification.TicketboxNotifier
import com.ticketbox.notification.budget.BudgetOverspendDispatchOutcome
import com.ticketbox.notification.budget.SharedPrefsBudgetOverspendStore
import com.ticketbox.notification.budget.budgetOverspendSentKey
import com.ticketbox.viewmodel.BudgetViewModel
import com.ticketbox.viewmodel.StatsBudgetViewModel
import java.io.IOException
import java.util.TimeZone
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.withTimeoutOrNull
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Real repository graph and disk Room; control only the budget HTTP response. */
@RunWith(AndroidJUnit4::class)
class BudgetOfflineSnapshotConnectedTest {
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val transport = OfflineBudgetTransport()
    private val fixture = ExpenseCorrectionConnectedFixture(context, transport::wrap)

    @After fun close() = fixture.close()

    @Test fun septemberUnknownValuesSurviveReopenButAnotherMonthTimezoneAndRefusalCannotBorrowThem() = runBlocking {
        transport.original = offlineBudget().copy(fixedAmountCents = null, flexBudgetCents = null,
            spentAmountCents = null, remainingAmountCents = null, overspentAmountCents = null,
            missingCurrencyCodes = listOf("USD"))
        val fresh = fixture.reopen().budgetRepository.monthlyBudget("2026-09", timezone = "Asia/Shanghai").getOrThrow()
        assertTrue(!fresh.fromCache)
        val originalIntents = fixture.stored()
        transport.offline = true
        val repository = fixture.reopen().budgetRepository

        val saved = repository.monthlyBudget("2026-09", timezone = "Asia/Shanghai")
        assertTrue("Previously read September must survive reopening disk Room offline", saved.isSuccess)
        assertEquals(transport.original.toDomain(), saved.getOrThrow().value)
        assertEquals(fresh.fetchedAt, saved.getOrThrow().fetchedAt)
        assertTrue(saved.getOrThrow().fromCache)
        assertTrue(repository.monthlyBudget("2026-10", timezone = "Asia/Shanghai").isFailure)
        assertTrue(repository.monthlyBudget("2026-09", timezone = "America/Los_Angeles").isFailure)

        transport.denied = true
        assertTrue(repository.monthlyBudget("2026-09", timezone = "Asia/Shanghai").isFailure)
        transport.denied = false
        assertTrue("The refused snapshot must not return when the transport fails again",
            repository.monthlyBudget("2026-09", timezone = "Asia/Shanghai").isFailure)
        assertEquals(originalIntents, fixture.stored())
    }

    @Test fun anUnconfiguredMonthWithNullableVersionRemainsAnOriginalOfflineRead() = runBlocking {
        transport.original = offlineBudget().copy(configured = false, rowVersion = null, homeCurrencyCode = null,
            totalAmountCents = 0, categoryBudgets = emptyList())
        val fresh = fixture.reopen().budgetRepository.monthlyBudget("2026-09").getOrThrow()
        transport.offline = true

        val reopened = fixture.reopen().budgetRepository.monthlyBudget("2026-09").getOrThrow()

        assertEquals(transport.original.toDomain(), reopened.value)
        assertEquals(fresh.fetchedAt, reopened.fetchedAt)
        assertTrue(reopened.fromCache)
        assertTrue(!reopened.value.configured)
    }

    @Test fun replacingTheBindingCannotExposeTheOriginalMonthlyBudget() = runBlocking {
        fixture.reopen().budgetRepository.monthlyBudget("2026-09").getOrThrow()
        transport.offline = true
        val repository = fixture.reopen().budgetRepository
        assertTrue("First establish the saved read under its original binding", repository.monthlyBudget("2026-09").isSuccess)

        fixture.switchLedger()

        assertTrue(repository.monthlyBudget("2026-09").isFailure)
    }

    @Test fun theSameLedgerDoesNotShareAnOfflineReadAcrossAccountsOrDevices() = runBlocking {
        for (replacePrincipal in listOf(fixture::switchAccount, fixture::switchDevice)) {
            transport.offline = false
            fixture.reopen().budgetRepository.monthlyBudget("2026-09").getOrThrow()
            transport.offline = true
            val repository = fixture.reopen().budgetRepository
            assertTrue(repository.monthlyBudget("2026-09").isSuccess)

            replacePrincipal()

            assertTrue("The unchanged ledger ID cannot authorize another principal's saved read",
                repository.monthlyBudget("2026-09").isFailure)
        }
    }

    @Test fun aReadStartedBeforeRefusalCannotRepublishTheWithdrawnBudget() = runBlocking {
        val repository = fixture.reopen().budgetRepository
        repository.monthlyBudget("2026-09").getOrThrow()
        val started = CompletableDeferred<Unit>()
        val resume = CompletableDeferred<Unit>()
        transport.beforeNextRead = { started.complete(Unit); resume.await() }
        val olderRead = async { repository.monthlyBudget("2026-09") }
        started.await()
        transport.denied = true
        assertTrue(repository.monthlyBudget("2026-09").isFailure)
        transport.denied = false
        resume.complete(Unit)

        assertTrue("A response captured before refusal cannot restore the withdrawn query", olderRead.await().isFailure)
        transport.offline = true
        assertTrue(fixture.reopen().budgetRepository.monthlyBudget("2026-09").isFailure)
    }

    @Test fun anOfflineOverspendSnapshotCannotConsumeANewNotificationSentKey() = runBlocking {
        val graph = fixture.reopen()
        val calendars = fixture.ledgerCalendarRepository
        calendars.refresh(requireNotNull(calendars.currentBinding())).getOrThrow()
        val month = calendars.newTaskMonth()
        val queryTimezone = TimeZone.getDefault().id
        transport.original = offlineBudget().copy(spentAmountCents = 1500, remainingAmountCents = -300, overspentAmountCents = 300)
        graph.budgetRepository.monthlyBudget(month, timezone = queryTimezone).getOrThrow()
        transport.offline = true
        fixture.reopen()
        val runtime = NotificationRuntimeGraph(fixture.notificationDependencies.copy(settingsStore =
            object : TicketboxSettingsStore by fixture.settingsStore {
                override fun notificationPreferences() = NotificationPreferences(budgetOverspendAlerts = true)
            }))
        val key = budgetOverspendSentKey("correction-ledger", month)
        val preferences = context.getSharedPreferences(SharedPrefsBudgetOverspendStore.PREFS_NAME, Context.MODE_PRIVATE)
        val originalValue = if (preferences.contains(key)) preferences.getBoolean(key, false) else null
        preferences.edit().remove(key).commit()
        val manager = context.getSystemService(NotificationManager::class.java)
        val probeTag = "budget-offline-reading-delivery-probe"
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                InstrumentationRegistry.getInstrumentation().uiAutomation.grantRuntimePermission(
                    context.packageName, Manifest.permission.POST_NOTIFICATIONS)
            }
            // Prove a decision would reach SENT; disabled OS delivery must not make this test falsely green.
            assertEquals(BudgetOverspendDispatchOutcome.SENT, runtime.notifier.onBudgetOverspent("¥300", probeTag))
            val previousReads = transport.reads.size
            runtime.budgetOverspendChecker.checkNow("correction-ledger")
            assertEquals("The real graph must attempt its live budget query", previousReads + 1, transport.reads.size)
            assertEquals("Cache warmup and the real notification must address the same query",
                month to queryTimezone, transport.readScopes.last())
            assertTrue("The real graph must not mark a cached overspend as newly notified", !preferences.contains(key))
            assertTrue(manager.activeNotifications.none { it.tag == key })
        } finally {
            manager.cancel(probeTag, TicketboxNotifier.DRAFT_NOTIFICATION_ID)
            manager.cancel(key, TicketboxNotifier.DRAFT_NOTIFICATION_ID)
            if (originalValue == null) preferences.edit().remove(key).commit()
            else preferences.edit().putBoolean(key, originalValue).commit()
        }
    }

    @Test fun acceptedOriginalBudgetCannotBeDowngradedByAnOlderGetOrUsedAsAFreshQueryReceipt() = runBlocking {
        val graph = fixture.reopen()
        val repository = graph.budgetRepository
        repository.monthlyBudget("2026-09").getOrThrow()
        val started = CompletableDeferred<Unit>()
        val resume = CompletableDeferred<Unit>()
        transport.beforeNextRead = { started.complete(Unit); resume.await() }
        val olderRead = async { repository.monthlyBudget("2026-09") }
        started.await()
        val binding = requireNotNull(graph.expenseRepository.captureDeferredLedgerBinding())
        repository.enqueueSave(binding, "2026-09", BudgetMonthlyUpdate("JPY", 7, 2400)).getOrThrow()
        val originalIntent = fixture.stored().single()
        val accepted = transport.original.copy(rowVersion = 8, totalAmountCents = 2400, flexBudgetCents = 2400,
            remainingAmountCents = 1989, excludedCategories = emptyList(), categoryBudgets = emptyList())
        val api = object : ApiService by transport.service {
            override suspend fun updateMonthlyBudget(month: String, request: BudgetMonthlyUpdateRequestDto,
                timezone: String?, idempotencyKey: String?): com.ticketbox.data.remote.dto.BudgetMonthlyDto {
                assertEquals("2026-09", month)
                assertEquals(BudgetMonthlyUpdateRequestDto("JPY", 7, 2400), request)
                assertEquals(originalIntent["idempotencyKey"], idempotencyKey)
                transport.original = accepted
                return accepted
            }
        }
        val adapters = OutboxAdapterGraph()
        val outcome = try {
            OutboxDrainEngine(fixture.outbox, listOf(SaveMonthlyBudgetDispatcher(
                { api }, adapters.budgetSaveAdapter, adapters.budgetReceiptAdapter, repository::invalidateBudgetReadsAfterDelivery)), now = fixture.clock::millis).drainOnce()
        } finally { resume.complete(Unit) }
        assertEquals(1, outcome.done)
        val acceptedIntent = fixture.stored().single()
        assertEquals(PendingMutationStatus.Done.wireValue, acceptedIntent["status"])
        for (field in listOf("id", "type", "targetId", "payload", "idempotencyKey", "expectedRowVersion", "ownerKey", "ledgerId", "serverUrl")) {
            assertEquals("Accepted delivery must preserve the original $field", originalIntent[field], acceptedIntent[field])
        }
        assertTrue("A v7 GET captured before the accepted v8 command must not republish", olderRead.await().isFailure)
        transport.offline = true
        assertTrue("The v8 receipt is not a fresh monthly-budget query",
            fixture.reopen().budgetRepository.monthlyBudget("2026-09").isFailure)
        transport.offline = false
        assertEquals(accepted.toDomain(), fixture.graph.budgetRepository.monthlyBudget("2026-09").getOrThrow().value)
        transport.offline = true
        assertEquals(accepted.toDomain(), fixture.reopen().budgetRepository.monthlyBudget("2026-09").getOrThrow().value)
        assertEquals(acceptedIntent, fixture.stored().single())
    }

    @Test fun replayAfterLostSaveAckRetainsAnAlreadyReadAcceptedOrNewerQueryAndItsTime() = runBlocking {
        for (queryVersion in listOf(8L, 9L)) {
            transport.offline = false
            val graph = fixture.reopen()
            val repository = graph.budgetRepository
            val month = if (queryVersion == 8L) "2026-09" else "2026-10"
            transport.original = offlineBudget().copy(month = month)
            repository.monthlyBudget(month).getOrThrow()
            val binding = requireNotNull(graph.expenseRepository.captureDeferredLedgerBinding())
            val id = repository.enqueueSave(binding, month, BudgetMonthlyUpdate("JPY", 7, 2400)).getOrThrow()
            val original = fixture.stored().single { it["id"] == id.toString() }
            val receipt = transport.original.copy(rowVersion = 8, totalAmountCents = 2400, flexBudgetCents = 2400,
                remainingAmountCents = 1989, excludedCategories = emptyList(), categoryBudgets = emptyList())
            var writes = 0
            val api = object : ApiService by transport.service {
                override suspend fun updateMonthlyBudget(month: String, request: BudgetMonthlyUpdateRequestDto,
                    timezone: String?, idempotencyKey: String?): BudgetMonthlyDto {
                    assertEquals(original["idempotencyKey"], idempotencyKey)
                    assertEquals(BudgetMonthlyUpdateRequestDto("JPY", 7, 2400), request)
                    if (++writes == 1) { transport.original = receipt; throw IOException("Committed; ACK lost") }
                    return receipt
                }
            }
            val adapters = OutboxAdapterGraph()
            val engine = OutboxDrainEngine(fixture.outbox, listOf(SaveMonthlyBudgetDispatcher({ api },
                adapters.budgetSaveAdapter, adapters.budgetReceiptAdapter, repository::invalidateBudgetReadsAfterDelivery)),
                now = fixture.clock::millis)
            assertEquals(1, engine.drainOnce().retryable)
            transport.original = receipt.copy(rowVersion = queryVersion, spentAmountCents = 600, remainingAmountCents = 1800)
            val query = repository.monthlyBudget(month).getOrThrow()
            assertTrue(!query.fromCache)
            assertEquals(1, engine.drainOnce().done)
            assertEquals(2, writes)
            val settled = fixture.stored().single { it["id"] == id.toString() }
            for (field in listOf("payload", "idempotencyKey", "expectedRowVersion", "ownerKey", "ledgerId", "serverUrl")) {
                assertEquals("Replay must preserve original $field", original[field], settled[field])
            }
            assertEquals(receipt, adapters.budgetReceiptAdapter.fromJson(requireNotNull(settled["receiptJson"])))
            transport.offline = true
            val saved = fixture.reopen().budgetRepository.monthlyBudget(month)
            assertTrue("Receipt replay cannot delete an already queried v$queryVersion budget", saved.isSuccess)
            assertEquals(query.value, saved.getOrThrow().value)
            assertEquals(query.fetchedAt, saved.getOrThrow().fetchedAt)
            assertTrue(saved.getOrThrow().fromCache)
        }
    }

    @Test fun independentReadsSurviveALaterFailureAndLateOlderSuccessCannotDowngradeRoom() = runBlocking {
        val repository = fixture.reopen().budgetRepository
        val started = CompletableDeferred<Unit>()
        val resume = CompletableDeferred<Unit>()
        transport.beforeNextRead = { started.complete(Unit); resume.await() }
        val first = async { repository.monthlyBudget("2026-09") }
        started.await()
        transport.offline = true
        try {
            assertTrue("A later transport failure has no saved read to borrow", repository.monthlyBudget("2026-09").isFailure)
        } finally { resume.complete(Unit) }
        val successful = first.await()
        assertTrue("A failed independent request cannot cancel the earlier valid GET", successful.isSuccess)
        assertEquals(offlineBudget().toDomain(), successful.getOrThrow().value)
        assertEquals(successful.getOrThrow().fetchedAt,
            fixture.reopen().budgetRepository.monthlyBudget("2026-09").getOrThrow().fetchedAt)

        transport.offline = false
        val reopened = fixture.graph.budgetRepository
        val olderStarted = CompletableDeferred<Unit>()
        val releaseOlder = CompletableDeferred<Unit>()
        transport.beforeNextRead = { olderStarted.complete(Unit); releaseOlder.await() }
        val older = async { reopened.monthlyBudget("2026-09") }
        olderStarted.await()
        transport.original = offlineBudget().copy(rowVersion = 8, totalAmountCents = 2400, remainingAmountCents = 1989)
        val newer = try { reopened.monthlyBudget("2026-09").getOrThrow() } finally { releaseOlder.complete(Unit) }
        assertTrue("Both independent successful GET callers must remain successful", older.await().isSuccess)
        transport.offline = true
        val saved = fixture.reopen().budgetRepository.monthlyBudget("2026-09").getOrThrow()
        assertEquals("The late v7 response cannot replace the accepted v8 query", newer.value, saved.value)
        assertEquals(newer.fetchedAt, saved.fetchedAt)
        assertTrue(saved.fromCache)
    }

    @Test fun oneRefusedConsumerWithdrawsAllRetainedBudgetDisplaysWithoutTouchingOriginals() = runBlocking {
        val graph = fixture.reopen()
        val repository = graph.budgetRepository
        val models = ViewModelStore()
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        lateinit var plans: BudgetViewModel
        lateinit var editor: BudgetViewModel
        lateinit var insights: StatsBudgetViewModel
        try {
            instrumentation.runOnMainSync { plans = BudgetViewModel(repository, "2026-09"); models.put("plans", plans) }
            withTimeout(5_000) { plans.uiState.first { it.budget != null } }
            instrumentation.runOnMainSync { editor = BudgetViewModel(repository, "2026-09"); models.put("editor", editor) }
            withTimeout(5_000) { editor.uiState.first { it.budget != null } }
            instrumentation.runOnMainSync {
                insights = StatsBudgetViewModel(repository); models.put("insights", insights)
                insights.refresh("2026-09")
            }
            withTimeout(5_000) { insights.uiState.first { it.budgetProgress != null } }
            instrumentation.runOnMainSync { plans.updateTotalAmount("1300") }
            val draft = plans.uiState.value.form
            val binding = requireNotNull(graph.expenseRepository.captureDeferredLedgerBinding())
            val id = repository.enqueueSave(binding, "2026-09", BudgetMonthlyUpdate("JPY", 7, 1200)).getOrThrow()
            fixture.outbox.markFailed(id, "budget_delivery_unknown")
            val originalIntents = fixture.stored()
            transport.denied = true
            val readCount = transport.reads.size
            instrumentation.runOnMainSync { editor.refresh() }
            withTimeout(5_000) { editor.uiState.first { it.loadError != null && it.budget == null } }
            withTimeoutOrNull(2_000) {
                combine(plans.uiState, insights.uiState) { plan, stats -> plan.budget == null && stats.budgetProgress == null }
                    .first { it }
            }
            assertNull("Plans must withdraw without issuing another GET", plans.uiState.value.budget)
            assertNull(plans.uiState.value.fetchedAt)
            assertNull("Insights must withdraw without issuing another GET", insights.uiState.value.budgetProgress)
            assertNull(insights.uiState.value.fetchedAt)
            assertNull(editor.uiState.value.fetchedAt)
            assertEquals(readCount + 1, transport.reads.size)
            assertEquals(draft, plans.uiState.value.form)
            assertTrue(plans.uiState.value.formDirty)
            assertEquals(originalIntents, fixture.stored())
        } finally { instrumentation.runOnMainSync { models.clear() } }
    }
}
