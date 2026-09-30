package com.ticketbox

import android.content.Context
import android.os.SystemClock
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.repository.ApiServiceProvider
import com.ticketbox.data.repository.BudgetRepository
import com.ticketbox.data.repository.RecurringRepository
import com.ticketbox.data.repository.ServerStatusRepository
import com.ticketbox.notification.TicketboxNotifier
import com.ticketbox.notification.backup.BackupStaleEngine
import com.ticketbox.notification.backup.BackupStaleRuntime
import com.ticketbox.notification.backup.BackupStaleSource
import com.ticketbox.notification.backup.BackupStaleDispatcher
import com.ticketbox.notification.backup.SharedPrefsBackupStaleStore
import com.ticketbox.notification.backup.WorkManagerBackupStaleScheduler
import com.ticketbox.notification.budget.BudgetOverspendChecker
import com.ticketbox.notification.budget.BudgetOverspendRuntime
import com.ticketbox.notification.budget.BudgetOverspendSource
import com.ticketbox.notification.budget.BudgetOverspendDispatcher
import com.ticketbox.notification.budget.SharedPrefsBudgetOverspendStore
import com.ticketbox.notification.recurring.RecurringReminderDispatcher
import com.ticketbox.notification.recurring.RecurringReminderEngine
import com.ticketbox.notification.recurring.RecurringReminderPolicy
import com.ticketbox.notification.recurring.RecurringReminderRuntime
import com.ticketbox.notification.recurring.RepositoryRecurringReminderSource
import com.ticketbox.notification.recurring.SharedPrefsRecurringReminderStore
import com.ticketbox.notification.recurring.WorkManagerRecurringReminderScheduler
import java.time.LocalDate
import com.ticketbox.data.repository.LedgerCalendarRepository
import com.ticketbox.data.repository.newTaskMonth
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob

internal data class NotificationRuntimeDependencies(
    val appContext: Context,
    val settingsStore: TicketboxSettingsStore,
    val apiServiceProvider: ApiServiceProvider,
    val recurringRepository: RecurringRepository,
    val budgetRepository: BudgetRepository,
    val ledgerCalendarRepository: LedgerCalendarRepository,
)

internal class NotificationRuntimeGraph(
    private val dependencies: NotificationRuntimeDependencies,
) {

    val notifier = TicketboxNotifier(
        context = dependencies.appContext,
        settingsStore = dependencies.settingsStore,
        currentBinding = dependencies.ledgerCalendarRepository::currentBinding,
    )

    val recurringReminderScheduler = WorkManagerRecurringReminderScheduler()

    val recurringReminderEngine = RecurringReminderEngine(
        source = RepositoryRecurringReminderSource(dependencies.recurringRepository),
        policy = RecurringReminderPolicy(),
        store = SharedPrefsRecurringReminderStore(dependencies.appContext),
        dispatcher = RecurringReminderDispatcher(notifier::onRecurringDue),
        runtime = RecurringReminderRuntime(
            recurringRemindersEnabled = {
                dependencies.settingsStore.notificationPreferences().recurringReminders
            },
            activeBinding = dependencies.ledgerCalendarRepository::currentBinding,
            today = { LocalDate.now() },
        ),
    )

    val budgetOverspendChecker = BudgetOverspendChecker(
        source = BudgetOverspendSource { month ->
            dependencies.budgetRepository.monthlyBudget(
                month = month,
                timezone = com.ticketbox.data.repository.currentBudgetTimezoneId(),
                freshOnly = true,
            ).map { it.value }
        },
        store = SharedPrefsBudgetOverspendStore(dependencies.appContext),
        dispatcher = BudgetOverspendDispatcher(notifier::onBudgetOverspent),
        runtime = BudgetOverspendRuntime(
            budgetOverspendAlertsEnabled = {
                dependencies.settingsStore.notificationPreferences().budgetOverspendAlerts
            },
            currentMonth = { dependencies.ledgerCalendarRepository.newTaskMonth() },
            activeBinding = dependencies.ledgerCalendarRepository::currentBinding,
            monotonicNowMillis = { SystemClock.elapsedRealtime() },
        ),
        scope = CoroutineScope(SupervisorJob() + Dispatchers.IO),
    )

    val backupStaleScheduler = WorkManagerBackupStaleScheduler()

    val serverStatusRepository = ServerStatusRepository(
        apiProvider = dependencies.apiServiceProvider,
    )

    val backupStaleEngine = BackupStaleEngine(
        source = BackupStaleSource { serverStatusRepository.backupHealth() },
        store = SharedPrefsBackupStaleStore(dependencies.appContext),
        dispatcher = BackupStaleDispatcher(notifier::onBackupStale),
        runtime = BackupStaleRuntime(
            backupStaleAlertsEnabled = {
                dependencies.settingsStore.notificationPreferences().backupStaleAlerts
            },
            activeBinding = dependencies.ledgerCalendarRepository::currentBinding,
            today = { LocalDate.now() },
        ),
    )
}
