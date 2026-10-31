package com.ticketbox.widget

import android.appwidget.AppWidgetManager
import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.ticketbox.TicketboxApplication
import com.ticketbox.data.repository.readWidgetMonthlySummary
import com.ticketbox.security.isBusinessReady
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.TimeUnit

class WidgetUpdateWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val publication = publicationRevision.get()
        val context = applicationContext
        val container = (context as TicketboxApplication).container
        val session = container.sessionStore.currentSession()
        val preferences = WidgetPreferences(context)
        if (!session.isBusinessReady() || overviewWidgetIds(context).none { preferences.allowsSummary(it, session?.version) }) {
            renderWidgetPlaceholders(context)
            cancel(context, removePeriodic = true)
            return Result.success()
        }
        val snapshot = readWidgetMonthlySummary(container.expenseRepository, container.ledgerCalendarRepository).getOrNull()
        withContext(Dispatchers.Main.immediate) {
            // A late response never repaints a signed-out or newly selected ledger.
            if (isStopped || publication != publicationRevision.get() ||
                container.sessionStore.currentSession()?.version != session?.version) return@withContext
            val manager = AppWidgetManager.getInstance(context)
            overviewWidgetIds(context).forEach { id ->
                val visible = preferences.allowsSummary(id, session?.version)
                manager.updateAppWidget(id, monthlyOverviewViews(context, id,
                    WidgetOverviewState(session, snapshot, visible, loading = false)))
            }
        }
        return Result.success()
    }

    companion object {
        internal const val WORK_NAME = "home-widget-summary"
        internal const val PERIODIC_WORK_NAME = "home-widget-summary-periodic"
        // WorkManager cancellation is asynchronous; retire the old display result immediately.
        private val publicationRevision = AtomicLong()

        internal fun enqueue(context: Context) {
            val session = (context.applicationContext as TicketboxApplication).container.sessionStore.currentSession()
            val preferences = WidgetPreferences(context)
            if (!session.isBusinessReady() || overviewWidgetIds(context).none { preferences.allowsSummary(it, session?.version) }) {
                cancel(context, removePeriodic = true)
                renderWidgetPlaceholders(context)
                return
            }
            publicationRevision.incrementAndGet()
            val work = WorkManager.getInstance(context)
            // Keep one scheduled refresh. Cycling WorkManager's last pending job toggles
            // RescheduleReceiver, whose PACKAGE_CHANGED broadcast refreshes widget providers.
            work.enqueueUniquePeriodicWork(PERIODIC_WORK_NAME, ExistingPeriodicWorkPolicy.KEEP,
                PeriodicWorkRequestBuilder<WidgetUpdateWorker>(30, TimeUnit.MINUTES)
                    .setInitialDelay(30, TimeUnit.MINUTES).build())
            work.enqueueUniqueWork(
                WORK_NAME, ExistingWorkPolicy.REPLACE, OneTimeWorkRequestBuilder<WidgetUpdateWorker>().build(),
            )
        }

        internal fun cancel(context: Context, removePeriodic: Boolean = false) {
            publicationRevision.incrementAndGet()
            val work = WorkManager.getInstance(context)
            work.cancelUniqueWork(WORK_NAME)
            if (removePeriodic) work.cancelUniqueWork(PERIODIC_WORK_NAME)
        }
    }
}
