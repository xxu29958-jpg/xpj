package com.ticketbox.widget

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.widget.RemoteViews
import com.ticketbox.MainActivity
import com.ticketbox.R
import com.ticketbox.data.repository.ReadSnapshot
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.presentation.formatDisplayAmount
import com.ticketbox.security.LocalSessionRecord
import com.ticketbox.security.isBusinessReady
import com.ticketbox.ui.navigation.ACTION_SHORTCUT
import com.ticketbox.ui.navigation.EXTRA_SHORTCUT_TARGET
import com.ticketbox.ui.navigation.ShortcutTarget
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

internal data class WidgetOverviewState(
    val session: LocalSessionRecord?,
    val snapshot: ReadSnapshot<MonthlyStats>? = null,
    val showSummary: Boolean = false,
    val loading: Boolean = true,
)

internal fun quickEntryViews(context: Context): RemoteViews = RemoteViews(context.packageName, R.layout.widget_quick_entry)
    .apply {
        bindQuickActions(context)
        setOnClickPendingIntent(R.id.widget_camera, launchPendingIntent(context, ShortcutTarget.CaptureReceipt))
        setOnClickPendingIntent(R.id.widget_templates, launchPendingIntent(context, ShortcutTarget.EntryTemplates))
    }

internal fun widgetLaunchIntent(context: Context, target: ShortcutTarget): Intent =
    Intent(context, MainActivity::class.java).apply {
        action = ACTION_SHORTCUT
        // Extras do not distinguish PendingIntents. Each action needs a stable identity.
        data = Uri.parse("ticketbox-widget://${context.packageName}/${target.id}")
        putExtra(EXTRA_SHORTCUT_TARGET, target.id)
        flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP
    }

internal fun launchPendingIntent(context: Context, target: ShortcutTarget): PendingIntent = PendingIntent.getActivity(
    context, 0, widgetLaunchIntent(context, target), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
)

private fun RemoteViews.bindQuickActions(context: Context) {
    setOnClickPendingIntent(R.id.widget_manual, launchPendingIntent(context, ShortcutTarget.ManualEntry))
    setOnClickPendingIntent(R.id.widget_upload, launchPendingIntent(context, ShortcutTarget.UploadReceipt))
    setOnClickPendingIntent(R.id.widget_review, launchPendingIntent(context, ShortcutTarget.ReviewPending))
}

internal fun monthlyOverviewViews(context: Context, id: Int, state: WidgetOverviewState): RemoteViews =
    RemoteViews(context.packageName, R.layout.widget_monthly_overview).apply {
        bindQuickActions(context)
        setOnClickPendingIntent(R.id.widget_summary, launchPendingIntent(context, ShortcutTarget.MonthlyOverview))
        bindSummary(context, state)
        bindWidgetControls(context, id, WidgetKind.Monthly, state.showSummary)
    }

private fun RemoteViews.bindSummary(context: Context, state: WidgetOverviewState) {
    val snapshot = state.snapshot.takeIf { state.showSummary && state.session.isBusinessReady() }
    val stats = snapshot?.value
    val title = stats?.let { context.getString(R.string.widget_month_total, it.month, it.homeCurrencyCode) }
        ?: context.getString(R.string.widget_overview_name)
    val amount = summaryAmount(context, state, stats)
    val detail = stats?.let {
        context.getString(R.string.widget_bill_count, it.count) +
            if ((it.undatedExpenseCount ?: 0) > 0) context.getString(R.string.widget_undated_count, it.undatedExpenseCount) else ""
    } ?: context.getString(R.string.widget_open_details)
    setTextViewText(R.id.widget_title, title)
    setTextViewText(R.id.widget_amount, amount)
    setTextViewText(R.id.widget_detail, detail)
    setTextViewText(R.id.widget_ledger, state.session?.identity?.ledgerName.takeIf { snapshot != null }
        ?: context.getString(R.string.widget_brand))
    setTextViewText(R.id.widget_updated, snapshot?.let { snapshotTime(context, it) }
        ?: context.getString(R.string.widget_configure_hint))
    setContentDescription(R.id.widget_summary, "$title，$amount，$detail")
}

private fun summaryAmount(context: Context, state: WidgetOverviewState, stats: MonthlyStats?): String = when {
    !state.session.isBusinessReady() -> context.getString(R.string.widget_bind_first)
    !state.showSummary -> context.getString(R.string.widget_amount_hidden)
    stats == null -> context.getString(if (state.loading) R.string.widget_loading else R.string.widget_unavailable)
    stats.totalAmountCents == null || stats.missingRates.isNotEmpty() -> context.getString(R.string.widget_missing_rates)
    else -> formatDisplayAmount(stats.totalAmountCents, CurrencyDisplay.forRecord(stats.homeCurrencyCode))
}

private fun snapshotTime(context: Context, snapshot: ReadSnapshot<MonthlyStats>): String {
    val time = DateTimeFormatter.ofPattern("MM-dd HH:mm", Locale.getDefault())
        .withZone(ZoneId.systemDefault()).format(Instant.parse(snapshot.fetchedAt))
    return context.getString(if (snapshot.fromCache) R.string.widget_cached_at else R.string.widget_updated_at, time)
}
