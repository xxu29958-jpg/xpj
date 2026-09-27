package com.ticketbox.ui.navigation

import android.Manifest
import android.app.NotificationManager
import android.content.Context
import android.os.Build
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.NotificationRuntimeGraph
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.BudgetMonthlyUpdateRequestDto
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
import java.util.TimeZone
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
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
        fixture.reopen().budgetRepository.monthlyBudget("2026-09", timezone = "Asia/Shanghai").getOrThrow()
        val originalIntents = fixture.stored()
        transport.offline = true
        val repository = fixture.reopen().budgetRepository

        val saved = repository.monthlyBudget("2026-09", timezone = "Asia/Shanghai")
        assertTrue("Previously read September must survive reopening disk Room offline", saved.isSuccess)
        assertEquals(transport.original.toDomain(), saved.getOrThrow())
        assertTrue(repository.monthlyBudget("2026-10", timezone = "Asia/Shanghai").isFailure)
        assertTrue(repository.monthlyBudget("2026-09", timezone = "America/Los_Angeles").isFailure)

        transport.denied = true
        assertTrue(repository.monthlyBudget("2026-09", timezone = "Asia/Shanghai").isFailure)
        transport.denied = false
        assertTrue("The refused snapshot must not return when the transport fails again",
            repository.monthlyBudget("2026-09", timezone = "Asia/Shanghai").isFailure)
        assertEquals(originalIntents, fixture.stored())
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
                { api }, adapters.budgetSaveAdapter, adapters.budgetReceiptAdapter)), now = fixture.clock::millis).drainOnce()
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
        assertEquals(accepted.toDomain(), fixture.graph.budgetRepository.monthlyBudget("2026-09").getOrThrow())
        transport.offline = true
        assertEquals(accepted.toDomain(), fixture.reopen().budgetRepository.monthlyBudget("2026-09").getOrThrow())
        assertEquals(acceptedIntent, fixture.stored().single())
    }
}
