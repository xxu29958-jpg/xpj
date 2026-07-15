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
import com.ticketbox.notification.backup.NotifierBackupStaleDispatcher
import com.ticketbox.notification.backup.SharedPrefsBackupStaleStore
import com.ticketbox.notification.backup.WorkManagerBackupStaleScheduler
import com.ticketbox.notification.budget.BudgetOverspendChecker
import com.ticketbox.notification.budget.BudgetOverspendRuntime
import com.ticketbox.notification.budget.BudgetOverspendSource
import com.ticketbox.notification.budget.NotifierBudgetOverspendDispatcher
import com.ticketbox.notification.budget.SharedPrefsBudgetOverspendStore
import com.ticketbox.notification.recurring.NotifierRecurringReminderDispatcher
import com.ticketbox.notification.recurring.RecurringReminderEngine
import com.ticketbox.notification.recurring.RecurringReminderPolicy
import com.ticketbox.notification.recurring.RecurringReminderRuntime
import com.ticketbox.notification.recurring.RepositoryRecurringReminderSource
import com.ticketbox.notification.recurring.SharedPrefsRecurringReminderStore
import com.ticketbox.notification.recurring.WorkManagerRecurringReminderScheduler
import com.ticketbox.security.LocalSessionStore
import java.time.LocalDate
import java.time.YearMonth
import java.time.ZoneId
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob

internal data class NotificationRuntimeDependencies(
    val appContext: Context,
    val settingsStore: TicketboxSettingsStore,
    val sessionStore: LocalSessionStore,
    val apiServiceProvider: ApiServiceProvider,
    val recurringRepository: RecurringRepository,
    val budgetRepository: BudgetRepository,
)

internal class NotificationRuntimeGraph(
    private val dependencies: NotificationRuntimeDependencies,
) {
    private val budgetOverspendZone = ZoneId.of("Asia/Shanghai")

    val notifier = TicketboxNotifier(
        context = dependencies.appContext,
        settingsStore = dependencies.settingsStore,
    )

    val recurringReminderScheduler = WorkManagerRecurringReminderScheduler()

    val recurringReminderEngine = RecurringReminderEngine(
        source = RepositoryRecurringReminderSource(dependencies.recurringRepository),
        policy = RecurringReminderPolicy(),
        store = SharedPrefsRecurringReminderStore(dependencies.appContext),
        dispatcher = NotifierRecurringReminderDispatcher(notifier::onRecurringDue),
        runtime = RecurringReminderRuntime(
            recurringRemindersEnabled = {
                dependencies.settingsStore.notificationPreferences().recurringReminders
            },
            sessionReady = {
                dependencies.sessionStore.currentSession() != null
            },
            today = { LocalDate.now() },
        ),
    )

    val budgetOverspendChecker = BudgetOverspendChecker(
        source = BudgetOverspendSource { month ->
            dependencies.budgetRepository.monthlyBudget(
                month = month,
                timezone = budgetOverspendZone.id,
            )
        },
        store = SharedPrefsBudgetOverspendStore(dependencies.appContext),
        dispatcher = NotifierBudgetOverspendDispatcher(notifier::onBudgetOverspent),
        runtime = BudgetOverspendRuntime(
            budgetOverspendAlertsEnabled = {
                dependencies.settingsStore.notificationPreferences().budgetOverspendAlerts
            },
            activeLedgerId = {
                dependencies.sessionStore.currentSession()?.identity?.ledgerId
            },
            currentMonth = { YearMonth.now(budgetOverspendZone).toString() },
            monotonicNowMillis = { SystemClock.elapsedRealtime() },
        ),
        scope = CoroutineScope(SupervisorJob() + Dispatchers.IO),
    )

    val backupStaleScheduler = WorkManagerBackupStaleScheduler()

    private val serverStatusRepository = ServerStatusRepository(
        apiProvider = dependencies.apiServiceProvider,
    )

    val backupStaleEngine = BackupStaleEngine(
        source = BackupStaleSource { serverStatusRepository.backupHealth() },
        store = SharedPrefsBackupStaleStore(dependencies.appContext),
        dispatcher = NotifierBackupStaleDispatcher(notifier::onBackupStale),
        runtime = BackupStaleRuntime(
            backupStaleAlertsEnabled = {
                dependencies.settingsStore.notificationPreferences().backupStaleAlerts
            },
            sessionReady = {
                dependencies.sessionStore.currentSession() != null
            },
            today = { LocalDate.now() },
        ),
    )
}
