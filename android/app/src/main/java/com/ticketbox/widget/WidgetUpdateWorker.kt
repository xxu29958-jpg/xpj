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
import com.ticketbox.data.repository.readWidgetSpendingTrend
import com.ticketbox.data.repository.ReadSnapshot
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.security.LocalSessionRecord
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.withTimeoutOrNull
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
        val kinds = dataWidgetInstances(context).filterKeys { preferences.allowsSummary(it, session?.version) }.values.toSet()
        if (!session.isBusinessReady() || kinds.isEmpty()) {
            renderWidgetPlaceholders(context)
            cancel(context, removePeriodic = true)
            return Result.success()
        }
        val binding = container.expenseRepository.statsBinding() ?: return Result.success()
        val queue = if (WidgetKind.Tasks in kinds || WidgetKind.Sync in kinds) withTimeoutOrNull(3_000) {
            container.outboxRepository.observeStatus().first {
                it.binding?.owner?.storageKey == binding.ownerKey && it.binding?.ledgerId == binding.ledgerId
            }
        } else null
        publish(session, publication, null, WidgetExtraData(queue = queue), loading = true)
        val snapshot = if (WidgetKind.Monthly in kinds)
            readWidgetMonthlySummary(container.expenseRepository, container.ledgerCalendarRepository).getOrNull() else null
        val pending = if (WidgetKind.Tasks in kinds) container.expenseRepository.dataQualitySummary().getOrNull() else null
        val trend = if (WidgetKind.Trend in kinds)
            readWidgetSpendingTrend(container.reportsRepository, container.ledgerCalendarRepository, binding).getOrNull() else null
        publish(session, publication, snapshot, WidgetExtraData(queue, pending, trend), loading = false)
        return Result.success()
    }

    private suspend fun publish(session: LocalSessionRecord?, publication: Long, snapshot: ReadSnapshot<MonthlyStats>?,
        data: WidgetExtraData, loading: Boolean) {
        val context = applicationContext
        val container = (context as TicketboxApplication).container
        val preferences = WidgetPreferences(context)
        withContext(Dispatchers.Main.immediate) {
            // A late response never repaints a signed-out or newly selected ledger.
            if (isStopped || publication != publicationRevision.get() ||
                container.sessionStore.currentSession()?.version != session?.version) return@withContext
            val manager = AppWidgetManager.getInstance(context)
            dataWidgetInstances(context).forEach { (id, kind) ->
                val visible = preferences.allowsSummary(id, session?.version)
                val state = WidgetOverviewState(session, snapshot, visible, loading)
                manager.updateAppWidget(id, if (kind == WidgetKind.Monthly) monthlyOverviewViews(context, id, state)
                    else extraWidgetViews(context, id, kind, state, data))
            }
        }
    }

    companion object {
        internal const val WORK_NAME = "home-widget-summary"
        internal const val PERIODIC_WORK_NAME = "home-widget-summary-periodic"
        // WorkManager cancellation is asynchronous; retire the old display result immediately.
        private val publicationRevision = AtomicLong()

        internal fun enqueue(context: Context) {
            val session = (context.applicationContext as TicketboxApplication).container.sessionStore.currentSession()
            val preferences = WidgetPreferences(context)
            if (!session.isBusinessReady() || dataWidgetInstances(context).keys.none { preferences.allowsSummary(it, session?.version) }) {
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
