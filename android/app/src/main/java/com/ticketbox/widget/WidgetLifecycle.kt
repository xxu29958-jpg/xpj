package com.ticketbox.widget

import android.appwidget.AppWidgetManager
import android.content.Context
import com.ticketbox.AppContainer
import com.ticketbox.TicketboxApplication
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch

internal fun observeWidgetSession(context: Context, container: AppContainer, scope: CoroutineScope) {
    scope.launch {
        container.sessionStore.observeSession().map { it?.version to it?.identity }.distinctUntilChanged().drop(1).collect {
            renderWidgetPlaceholders(context)
            WidgetUpdateWorker.enqueue(context)
        }
    }
    scope.launch {
        container.expenseRepository.readAccessDenials.collect {
            WidgetUpdateWorker.cancel(context)
            renderWidgetPlaceholders(context, loading = false)
        }
    }
}

internal fun renderWidgetPlaceholders(context: Context, loading: Boolean = true) {
    val ids = overviewWidgetIds(context)
    if (ids.isEmpty()) return
    val session = (context.applicationContext as TicketboxApplication).container.sessionStore.currentSession()
    val preferences = WidgetPreferences(context)
    val manager = AppWidgetManager.getInstance(context)
    ids.forEach { id ->
        manager.updateAppWidget(id, monthlyOverviewViews(context, id,
            WidgetOverviewState(session, showSummary = preferences.allowsSummary(id, session?.version), loading = loading)))
    }
}
