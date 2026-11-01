package com.ticketbox.widget

import android.appwidget.AppWidgetManager
import android.content.Context
import com.ticketbox.AppContainer
import com.ticketbox.TicketboxApplication
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch

@OptIn(kotlinx.coroutines.FlowPreview::class)
internal fun observeWidgetSession(context: Context, container: AppContainer, scope: CoroutineScope) {
    // Serialize privacy resets with Worker publication on the main thread, so an
    // older update cannot race past a completed account/ledger reset.
    scope.launch(Dispatchers.Main.immediate) {
        container.sessionStore.observeSession().map { it?.version to it?.identity }.distinctUntilChanged().drop(1).collect {
            renderWidgetPlaceholders(context)
            WidgetUpdateWorker.enqueue(context)
        }
    }
    scope.launch(Dispatchers.Main.immediate) {
        container.expenseRepository.readAccessDenials.collect {
            WidgetUpdateWorker.cancel(context)
            renderWidgetPlaceholders(context, loading = false)
        }
    }
    scope.launch(Dispatchers.Main.immediate) {
        container.outboxRepository.observeStatus().map { status ->
            listOf(status.queueDepth, status.queuedRows.count { it.type == com.ticketbox.data.local.PendingMutationType.UploadScreenshot },
                status.failed.size, status.conflicts.size, status.quarantinedCount, status.refreshRequired.size)
        }.distinctUntilChanged().drop(1).debounce(400).collect {
            if (dataWidgetInstances(context).values.any { it == WidgetKind.Tasks || it == WidgetKind.Sync }) {
                WidgetUpdateWorker.enqueue(context)
            }
        }
    }
}

internal fun renderWidgetPlaceholders(context: Context, loading: Boolean = true) {
    val ids = dataWidgetInstances(context)
    if (ids.isEmpty()) return
    val session = (context.applicationContext as TicketboxApplication).container.sessionStore.currentSession()
    val preferences = WidgetPreferences(context)
    val manager = AppWidgetManager.getInstance(context)
    ids.forEach { (id, kind) ->
        val state = WidgetOverviewState(session, showSummary = preferences.allowsSummary(id, session?.version), loading = loading)
        manager.updateAppWidget(id, if (kind == WidgetKind.Monthly) monthlyOverviewViews(context, id, state)
            else extraWidgetViews(context, id, kind, state))
    }
}
