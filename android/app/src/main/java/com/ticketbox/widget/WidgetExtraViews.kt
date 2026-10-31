package com.ticketbox.widget

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.view.View
import android.widget.RemoteViews
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.OutboxStatus
import com.ticketbox.data.repository.WidgetSpendingTrend
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.DataQualitySummary
import com.ticketbox.presentation.formatDisplayAmount
import com.ticketbox.security.isBusinessReady
import com.ticketbox.ui.navigation.ShortcutTarget
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

internal data class WidgetExtraData(
    val queue: OutboxStatus? = null,
    val pending: DataQualitySummary? = null,
    val trend: WidgetSpendingTrend? = null,
)

internal fun RemoteViews.bindWidgetControls(context: Context, id: Int, kind: WidgetKind, visible: Boolean) {
    val flags = PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
    fun configure(reveal: Boolean) = Intent(context, WidgetConfigurationActivity::class.java)
        .putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, id)
        .putExtra(WidgetConfigurationActivity.EXTRA_REVEAL, reveal)
        .setData(Uri.parse("ticketbox-widget://${context.packageName}/${if (reveal) "reveal" else "configure"}/$id"))
    setOnClickPendingIntent(R.id.widget_configure, PendingIntent.getActivity(context, id, configure(false), flags))
    setOnClickPendingIntent(R.id.widget_refresh, PendingIntent.getBroadcast(context, id,
        Intent(context, kind.provider).setAction(DataWidgetProvider.ACTION_REFRESH), flags))
    val privacy = if (visible) PendingIntent.getBroadcast(context, id,
        Intent(context, kind.provider).setAction(DataWidgetProvider.ACTION_HIDE)
            .putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, id).setData(Uri.parse("ticketbox-widget://${context.packageName}/hide/$id")), flags)
    else PendingIntent.getActivity(context, id, configure(true), flags)
    setOnClickPendingIntent(R.id.widget_privacy, privacy)
    setImageViewResource(R.id.widget_privacy, if (visible) R.drawable.ic_lucide_eye_off else R.drawable.ic_lucide_eye)
    setContentDescription(R.id.widget_privacy, context.getString(if (visible) R.string.widget_hide else R.string.widget_reveal))
}

internal fun extraWidgetViews(
    context: Context,
    id: Int,
    kind: WidgetKind,
    state: WidgetOverviewState,
    data: WidgetExtraData = WidgetExtraData(),
): RemoteViews = RemoteViews(context.packageName,
    when (kind) {
        WidgetKind.Trend -> R.layout.widget_spending_trend
        WidgetKind.Sync -> R.layout.widget_sync
        else -> R.layout.widget_queue
    }).apply {
    val visible = state.showSummary && state.session.isBusinessReady()
    bindWidgetControls(context, id, kind, visible)
    setTextViewText(R.id.widget_ledger, context.getString(kind.title))
    val message = when {
        !state.session.isBusinessReady() -> R.string.widget_bind_first
        !visible -> R.string.widget_data_hidden
        state.loading -> R.string.widget_loading
        else -> R.string.widget_unavailable
    }
    setTextViewText(R.id.widget_status, context.getString(message))
    setTextViewText(R.id.widget_updated, context.getString(R.string.widget_configure_hint))
    if (kind == WidgetKind.Trend) bindTrend(context, data.trend.takeIf { visible })
    else bindQueue(context, kind, data.takeIf { visible } ?: WidgetExtraData())
}

private fun RemoteViews.bindQueue(context: Context, kind: WidgetKind, data: WidgetExtraData) {
    val queue = data.queue
    val uploads = queue?.queuedRows?.count { it.type == PendingMutationType.UploadScreenshot }
    val first = if (kind == WidgetKind.Tasks) data.pending?.pendingTotal else uploads
    val second = if (kind == WidgetKind.Tasks) uploads else queue?.queuedRows?.count { it.type != PendingMutationType.UploadScreenshot }
    val firstLabel = if (kind == WidgetKind.Tasks) R.string.widget_pending_review else R.string.widget_pending_upload
    val secondLabel = if (kind == WidgetKind.Tasks) R.string.widget_pending_upload else R.string.widget_pending_record
    setTextViewText(R.id.widget_first_count, first?.toString() ?: "—")
    setTextViewText(R.id.widget_second_count, second?.toString() ?: "—")
    setTextViewText(R.id.widget_third_count, queue?.failed?.size?.toString() ?: "—")
    setTextViewText(R.id.widget_first_label, context.getString(firstLabel))
    setTextViewText(R.id.widget_second_label, context.getString(secondLabel))
    setTextViewText(R.id.widget_third_label, context.getString(R.string.widget_failed))
    setOnClickPendingIntent(R.id.widget_first, launchPendingIntent(context,
        if (kind == WidgetKind.Tasks) ShortcutTarget.ReviewPending else ShortcutTarget.PendingUploads))
    setOnClickPendingIntent(R.id.widget_second, launchPendingIntent(context,
        if (kind == WidgetKind.Tasks) ShortcutTarget.PendingUploads else ShortcutTarget.PendingRecords))
    setOnClickPendingIntent(R.id.widget_third, launchPendingIntent(context, ShortcutTarget.FailedOperations))
    bindQueueDetails(context, kind, data)
}

private fun RemoteViews.bindQueueDetails(context: Context, kind: WidgetKind, data: WidgetExtraData) {
    val queue = data.queue ?: return
        val attention = queue.conflicts.size + queue.quarantinedCount + queue.refreshRequired.size
        setTextViewText(R.id.widget_status, context.getString(if (attention > 0) R.string.widget_queue_attention else R.string.widget_local_queue, attention))
        setOnClickPendingIntent(R.id.widget_status, launchPendingIntent(context, ShortcutTarget.SyncStatus))
        setTextViewText(R.id.widget_updated, if (kind == WidgetKind.Tasks) data.pending?.let {
            context.getString(R.string.widget_todo_updated, widgetTime(it.generatedAt))
        } ?: context.getString(R.string.widget_pending_unavailable) else context.getString(R.string.widget_local_queue))
}

private fun RemoteViews.bindTrend(context: Context, trend: WidgetSpendingTrend?) {
    setOnClickPendingIntent(R.id.widget_trend_content, launchPendingIntent(context, ShortcutTarget.MonthlyOverview))
    setViewVisibility(R.id.widget_chart, if (trend == null) View.GONE else View.VISIBLE)
    setTextViewText(R.id.widget_comparison, "")
    if (trend == null) return
    val currency = CurrencyDisplay.forRecord(trend.currencyCode)
    setTextViewText(R.id.widget_status, context.getString(R.string.widget_trend_title, trend.currencyCode))
    setImageViewBitmap(R.id.widget_chart, widgetTrendChart(context, trend))
    setContentDescription(R.id.widget_chart, trend.days.joinToString("，") { day ->
        day.amountMinor?.let { "${day.date} ${formatDisplayAmount(it, currency)}" }
            ?: context.getString(R.string.widget_trend_missing_day, day.date.toString())
    })
    val comparison = if (trend.currentWeek != null && trend.previousWeek != null) {
        val change = runCatching { Math.subtractExact(trend.currentWeek, trend.previousWeek) }.getOrNull()
        context.getString(R.string.widget_week_total, formatDisplayAmount(trend.currentWeek, currency)) + "\n" +
            (change?.let { context.getString(R.string.widget_week_delta, (if (it > 0) "+" else "") + formatDisplayAmount(it, currency)) }
                ?: context.getString(R.string.widget_trend_incomplete))
    } else context.getString(R.string.widget_trend_incomplete)
    setTextViewText(R.id.widget_comparison, comparison)
    setTextViewText(R.id.widget_updated, context.getString(R.string.widget_updated_at, widgetTime(trend.fetchedAt)))
}

private fun widgetTime(value: String): String = runCatching {
    DateTimeFormatter.ofPattern("MM-dd HH:mm").withZone(ZoneId.systemDefault()).format(Instant.parse(value))
}.getOrDefault("—")
