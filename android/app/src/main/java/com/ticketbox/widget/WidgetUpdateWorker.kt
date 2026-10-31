package com.ticketbox.widget

import android.appwidget.AppWidgetManager
import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.ticketbox.TicketboxApplication
import com.ticketbox.data.repository.readWidgetMonthlySummary
import com.ticketbox.security.isBusinessReady
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.util.concurrent.atomic.AtomicLong

class WidgetUpdateWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val publication = publicationRevision.get()
        val context = applicationContext
        val container = (context as TicketboxApplication).container
        val session = container.sessionStore.currentSession()
        val preferences = WidgetPreferences(context)
        if (!session.isBusinessReady() || overviewWidgetIds(context).none { preferences.allowsSummary(it, session?.version) }) {
            renderWidgetPlaceholders(context)
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
        private const val WORK_NAME = "home-widget-summary"
        // WorkManager cancellation is asynchronous; retire the old display result immediately.
        private val publicationRevision = AtomicLong()

        internal fun enqueue(context: Context) {
            if (overviewWidgetIds(context).isEmpty()) return
            publicationRevision.incrementAndGet()
            WorkManager.getInstance(context).enqueueUniqueWork(
                WORK_NAME, ExistingWorkPolicy.REPLACE, OneTimeWorkRequestBuilder<WidgetUpdateWorker>().build(),
            )
        }

        internal fun cancel(context: Context) {
            publicationRevision.incrementAndGet()
            WorkManager.getInstance(context).cancelUniqueWork(WORK_NAME)
        }
    }
}
