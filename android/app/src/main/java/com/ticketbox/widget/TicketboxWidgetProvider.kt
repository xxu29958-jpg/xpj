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

open class DataWidgetProvider : AppWidgetProvider() {
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) {
        refresh(context)
    }

    override fun onAppWidgetOptionsChanged(context: Context, manager: AppWidgetManager, id: Int, options: Bundle) {
        refresh(context)
    }

    override fun onReceive(context: Context, intent: Intent) {
        super.onReceive(context, intent)
        if (intent.action == ACTION_REFRESH) refresh(context)
        if (intent.action == ACTION_HIDE) {
            val id = intent.getIntExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, AppWidgetManager.INVALID_APPWIDGET_ID)
            if (AppWidgetManager.getInstance(context).getAppWidgetInfo(id)?.provider == ComponentName(context, javaClass)) {
                WidgetPreferences(context).remove(intArrayOf(id))
                refresh(context)
            }
        }
    }

    override fun onDeleted(context: Context, ids: IntArray) {
        WidgetPreferences(context).remove(ids)
        WidgetUpdateWorker.enqueue(context)
    }

    override fun onDisabled(context: Context) {
        WidgetUpdateWorker.enqueue(context)
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
        internal const val ACTION_HIDE = "com.ticketbox.widget.HIDE"
    }
}

class MonthlyOverviewWidgetProvider : DataWidgetProvider() {
    companion object { internal const val ACTION_REFRESH = DataWidgetProvider.ACTION_REFRESH }
}
class PendingTasksWidgetProvider : DataWidgetProvider()
class SyncStatusWidgetProvider : DataWidgetProvider()
class SpendingTrendWidgetProvider : DataWidgetProvider()

internal enum class WidgetKind(val provider: Class<out DataWidgetProvider>, val title: Int) {
    Monthly(MonthlyOverviewWidgetProvider::class.java, com.ticketbox.R.string.widget_overview_name),
    Tasks(PendingTasksWidgetProvider::class.java, com.ticketbox.R.string.widget_todo_name),
    Sync(SyncStatusWidgetProvider::class.java, com.ticketbox.R.string.widget_sync_name),
    Trend(SpendingTrendWidgetProvider::class.java, com.ticketbox.R.string.widget_trend_name),
}

internal fun dataWidgetInstances(context: Context): Map<Int, WidgetKind> {
    val manager = AppWidgetManager.getInstance(context)
    return WidgetKind.entries.flatMap { kind ->
        manager.getAppWidgetIds(ComponentName(context, kind.provider)).map { it to kind }
    }.toMap()
}

internal fun overviewWidgetIds(context: Context): IntArray = AppWidgetManager.getInstance(context)
    .getAppWidgetIds(ComponentName(context, MonthlyOverviewWidgetProvider::class.java))
