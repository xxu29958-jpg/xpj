package com.ticketbox.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.TextAutoSize
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.AddPhotoAlternate
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ticketbox.R
import com.ticketbox.domain.model.CategoryStats
import com.ticketbox.domain.model.DuplicateStatusValues
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.domain.model.isPendingReadyToConfirmDirectly
import com.ticketbox.domain.model.ledgerRoleLabel
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.asAmount
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.viewmodel.MonthlyStatsUiState
import com.ticketbox.viewmodel.PendingUiState
import com.ticketbox.viewmodel.StatsSource

data class TodayScreenState(
    val pending: PendingUiState,
    val monthly: MonthlyStatsUiState,
    val ledgerName: String?,
    val ledgerRole: String?,
) {
    val pendingCount: Int get() = pending.items.size
    val missingAmountCount: Int get() = pending.items.count { it.amountCents == null }
    val duplicateCount: Int get() = pending.items.count { it.duplicateStatus == DuplicateStatusValues.SUSPECTED }
    val readyToConfirmCount: Int
        get() = pending.items.count { it.isPendingReadyToConfirmDirectly() }
    val topCategory: CategoryStats?
        get() = monthly.categoryInsight?.let {
            CategoryStats(category = it.topCategory, amountCents = it.topAmountCents, count = 0)
        } ?: monthly.stats?.byCategory?.filter { it.amountCents > 0L }?.maxByOrNull { it.amountCents }
}

data class TodayActions(
    val onRefresh: () -> Unit,
    val onOpenPending: () -> Unit,
    val onOpenLedger: () -> Unit,
    val onOpenInsights: () -> Unit,
    val onUploadReceipt: () -> Unit,
    val onManualEntry: () -> Unit,
)

@Composable
fun TodayScreen(
    state: TodayScreenState,
    actions: TodayActions,
) {
    AppScrollableContent(
        role = AppPageRole.Pending,
        isRefreshing = state.pending.loading || state.monthly.loading,
        onRefresh = actions.onRefresh,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        item {
            AppPageHeader(
                title = stringResource(R.string.today_header_title),
                subtitle = stringResource(R.string.today_header_subtitle),
            )
        }
        item { TodayOverview(state = state) }
        item { TodayActionRow(state = state, actions = actions) }
        item { TodayWorkstream(state = state) }
        item { TodayMonthSignals(state = state) }
    }
}

@Composable
private fun TodayOverview(state: TodayScreenState) {
    val ledgerName = state.ledgerName?.takeIf { it.isNotBlank() }
        ?: stringResource(R.string.today_ledger_unknown)
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = AppSpacing.smallGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        TodayLedgerHeader(ledgerName = ledgerName, ledgerRole = state.ledgerRole)
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.20f))
        TodayMonthSummary(stats = state.monthly.stats)
    }
}

@Composable
private fun TodayLedgerHeader(
    ledgerName: String,
    ledgerRole: String?,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = stringResource(R.string.today_ledger_label),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelLarge,
        )
        Text(
            text = ledgerRoleLabel(ledgerRole),
            modifier = Modifier
                .clip(RoundedCornerShape(AppRadius.pill))
                .background(MaterialTheme.colorScheme.primary.copy(alpha = 0.12f))
                .padding(horizontal = AppSpacing.contentGap, vertical = AppSpacing.miniGap),
            color = MaterialTheme.colorScheme.primary,
            style = MaterialTheme.typography.labelSmall,
        )
    }
    Text(
        text = ledgerName,
        color = MaterialTheme.colorScheme.onSurface,
        style = MaterialTheme.typography.titleMedium,
        fontWeight = AppTextHierarchy.heading.weight,
        maxLines = 1,
        overflow = TextOverflow.Ellipsis,
    )
}

@Composable
private fun TodayMonthSummary(stats: MonthlyStats?) {
    val currencyDisplay = LocalCurrencyDisplay.current
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
        Text(
            text = stringResource(R.string.today_month_spend_label),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelMedium,
        )
        Text(
            text = stats?.totalAmountCents?.let { formatDisplayAmount(it, currencyDisplay) }
                ?: stringResource(R.string.today_month_empty_value),
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.titleLarge.asAmount(AppAmountRole.Hero),
            autoSize = TextAutoSize.StepBased(
                minFontSize = 22.sp,
                maxFontSize = AppAmountRole.Hero.role.size,
                stepSize = 1.sp,
            ),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            text = stringResource(R.string.today_month_count, stats?.count ?: 0),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelMedium.tabularNum(),
        )
    }
}

@Composable
private fun TodayActionRow(
    state: TodayScreenState,
    actions: TodayActions,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        AppPrimaryButton(
            text = stringResource(R.string.today_primary_upload),
            icon = Icons.Filled.AddPhotoAlternate,
            modifier = Modifier.weight(1f),
            enabled = !state.pending.readOnly && !state.pending.uploading,
            onClick = actions.onUploadReceipt,
        )
        QuietOutlinedButton(
            text = stringResource(R.string.today_primary_manual),
            leadingIcon = Icons.Filled.Add,
            modifier = Modifier.weight(1f),
            enabled = !state.pending.readOnly,
            onClick = actions.onManualEntry,
        )
    }
}

@Composable
private fun TodayWorkstream(state: TodayScreenState) {
    val pendingLine = if (state.pendingCount == 0) {
        stringResource(R.string.today_pending_empty)
    } else {
        stringResource(R.string.today_pending_attention, state.pendingCount, state.readyToConfirmCount)
    }
    TodaySignalSection(title = stringResource(R.string.today_section_work)) {
        TodaySignalRow(
            label = stringResource(R.string.today_metric_pending),
            value = stringResource(R.string.today_count_receipts, state.pendingCount),
            caption = pendingLine,
        )
        if (state.readyToConfirmCount > 0) {
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.24f))
            TodaySignalRow(
                label = stringResource(R.string.today_metric_ready),
                value = stringResource(R.string.today_count_receipts, state.readyToConfirmCount),
            )
        }
        if (state.missingAmountCount > 0 || state.duplicateCount > 0) {
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.24f))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            ) {
                if (state.missingAmountCount > 0) {
                    TodaySmallSignal(
                        label = stringResource(R.string.today_metric_missing_amount),
                        value = stringResource(R.string.today_count_receipts, state.missingAmountCount),
                        modifier = Modifier.weight(1f),
                    )
                }
                if (state.missingAmountCount > 0 && state.duplicateCount > 0) {
                    TodayVerticalDivider()
                }
                if (state.duplicateCount > 0) {
                    TodaySmallSignal(
                        label = stringResource(R.string.today_metric_duplicates),
                        value = stringResource(R.string.today_count_receipts, state.duplicateCount),
                        modifier = Modifier.weight(1f),
                    )
                }
            }
        }
    }
}

@Composable
private fun TodayMonthSignals(state: TodayScreenState) {
    val currencyDisplay = LocalCurrencyDisplay.current
    val topCategory = state.topCategory
    val recentUploadValue = state.monthly.lastUploadAt?.let(::displayTime)
        ?: stringResource(R.string.today_recent_upload_empty)
    val syncValue = when {
        state.monthly.loading -> stringResource(R.string.today_sync_loading)
        state.monthly.statsLoadError != null -> stringResource(R.string.today_sync_error)
        state.monthly.statsSource == StatsSource.LocalFallback -> stringResource(R.string.today_sync_local)
        state.monthly.statsSource == StatsSource.Backend -> stringResource(R.string.today_sync_ready)
        else -> stringResource(R.string.today_sync_idle)
    }
    TodaySignalSection(title = stringResource(R.string.today_section_month)) {
        TodaySignalRow(
            label = stringResource(R.string.today_metric_top_category),
            value = topCategory?.category ?: stringResource(R.string.today_top_category_empty),
            caption = topCategory?.amountCents?.let { formatDisplayAmount(it, currencyDisplay) },
        )
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.24f))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            TodaySmallSignal(
                label = stringResource(R.string.today_metric_recent_upload),
                value = recentUploadValue,
                modifier = Modifier.weight(1f),
            )
            TodayVerticalDivider()
            TodaySmallSignal(
                label = stringResource(R.string.today_metric_sync),
                value = syncValue,
                modifier = Modifier.weight(1f),
            )
        }
    }
}

@Composable
private fun TodaySignalSection(
    title: String,
    content: @Composable () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        Text(
            text = title,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelLarge,
            fontWeight = AppTextHierarchy.heading.weight,
        )
        content()
    }
}

@Composable
private fun TodaySignalRow(
    label: String,
    value: String,
    caption: String? = null,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = AppSpacing.miniGap),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
        ) {
            Text(
                text = label,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodyMedium,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            if (caption != null) {
                Text(
                    text = caption,
                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.72f),
                    style = MaterialTheme.typography.labelSmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        Text(
            text = value,
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.titleMedium.tabularNum(),
            fontWeight = AppTextHierarchy.heading.weight,
            autoSize = TextAutoSize.StepBased(
                minFontSize = 13.sp,
                maxFontSize = 20.sp,
                stepSize = 1.sp,
            ),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun TodaySmallSignal(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier.padding(vertical = AppSpacing.miniGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
    ) {
        Text(
            text = label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodyMedium,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            text = value,
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.titleMedium.tabularNum(),
            fontWeight = AppTextHierarchy.heading.weight,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun TodayVerticalDivider() {
    Box(
        modifier = Modifier
            .width(1.dp)
            .height(44.dp)
            .background(MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.20f)),
    )
}
