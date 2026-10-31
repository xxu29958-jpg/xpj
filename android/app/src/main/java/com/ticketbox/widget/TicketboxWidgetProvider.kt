package com.ticketbox.widget

import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Bundle

class QuickEntryWidgetProvider : AppWidgetProvider() {
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) {
        ids.forEach { manager.updateAppWidget(it, quickEntryViews(context)) }
    }
}

class MonthlyOverviewWidgetProvider : AppWidgetProvider() {
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) {
        refresh(context)
    }

    override fun onAppWidgetOptionsChanged(context: Context, manager: AppWidgetManager, id: Int, options: Bundle) {
        refresh(context)
    }

    override fun onReceive(context: Context, intent: Intent) {
        super.onReceive(context, intent)
        if (intent.action == ACTION_REFRESH) refresh(context)
    }

    override fun onDeleted(context: Context, ids: IntArray) {
        WidgetPreferences(context).remove(ids)
        WidgetUpdateWorker.enqueue(context)
    }

    override fun onDisabled(context: Context) {
        WidgetUpdateWorker.cancel(context, removePeriodic = true)
    }

    override fun onRestored(context: Context, oldIds: IntArray, newIds: IntArray) {
        // A restore is a new placement: do not transfer another launcher's display consent.
        WidgetPreferences(context).remove(oldIds + newIds)
    }

    private fun refresh(context: Context) {
        renderWidgetPlaceholders(context)
        WidgetUpdateWorker.enqueue(context)
    }

    companion object {
        internal const val ACTION_REFRESH = "com.ticketbox.widget.REFRESH"
    }
}

internal fun overviewWidgetIds(context: Context): IntArray = AppWidgetManager.getInstance(context)
    .getAppWidgetIds(ComponentName(context, MonthlyOverviewWidgetProvider::class.java))
