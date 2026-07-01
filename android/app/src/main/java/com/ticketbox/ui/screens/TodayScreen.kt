package com.ticketbox.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.TextAutoSize
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.AddPhotoAlternate
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ticketbox.R
import com.ticketbox.domain.model.DuplicateStatusValues
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.domain.model.isPendingReadyToConfirmDirectly
import com.ticketbox.domain.model.ledgerRoleLabel
import com.ticketbox.ui.components.AppDataAuthorityStrip
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.DataAuthorityTone
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAlpha
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

data class TodayTopCategory(
    val name: String,
    val amountCents: Long,
)

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
    val topCategory: TodayTopCategory?
        get() = monthly.categoryInsight?.let {
            TodayTopCategory(name = it.topCategory, amountCents = it.topAmountCents)
        } ?: monthly.stats?.byCategory
            ?.filter { it.amountCents > 0L }
            ?.maxByOrNull { it.amountCents }
            ?.let { TodayTopCategory(name = it.category, amountCents = it.amountCents) }
    val authorityTone: DataAuthorityTone?
        get() = when {
            pending.readOnly -> DataAuthorityTone.ReadOnly
            pending.loading || monthly.loading -> DataAuthorityTone.Refreshing
            pending.showingCachedSnapshot -> DataAuthorityTone.LocalCache
            monthly.statsSource == StatsSource.LocalFallback -> DataAuthorityTone.LocalCache
            monthly.statsSource == StatsSource.Backend -> DataAuthorityTone.Backend
            else -> null
        }
}

data class TodayActions(
    val onRefresh: () -> Unit,
    val onOpenPending: () -> Unit,
    val onOpenLedger: () -> Unit,
    val onOpenInsights: () -> Unit,
    val onUploadReceipt: () -> Unit,
    val onManualEntry: () -> Unit,
)

internal enum class TodayNextAction {
    MissingAmount,
    Duplicate,
    Ready,
    ReviewPending,
    UploadReceipt,
    OpenLedger,
}

private data class TodayNextActionCopy(
    val title: String,
    val caption: String,
    val buttonText: String,
)

@Composable
fun TodayScreen(
    state: TodayScreenState,
    actions: TodayActions,
) {
    AppScrollableContent(
        role = AppPageRole.Today,
        isRefreshing = TodayRefreshIndicator.isActive(
            pendingLoading = state.pending.loading,
            pendingLoadedOnce = state.pending.hasLoadedOnce,
            monthlyLoading = state.monthly.loading,
        ),
        onRefresh = actions.onRefresh,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        item {
            AppPageHeader(
                title = stringResource(R.string.today_header_title),
                subtitle = stringResource(R.string.today_header_subtitle),
            )
        }
        state.authorityTone?.takeIf { it != DataAuthorityTone.Backend }?.let { tone ->
            item {
                AppDataAuthorityStrip(tone = tone)
            }
        }
        item { TodayCockpit(state = state) }
        item { TodayActionRow(state = state, actions = actions) }
        item { TodayWorkstream(state = state, onOpenPending = actions.onOpenPending) }
        item {
            TodayMonthSignals(
                state = state,
                onOpenLedger = actions.onOpenLedger,
                onOpenInsights = actions.onOpenInsights,
            )
        }
    }
}

@Composable
private fun TodayCockpit(state: TodayScreenState) {
    val ledgerName = state.ledgerName?.takeIf { it.isNotBlank() }
        ?: stringResource(R.string.today_ledger_unknown)
    val syncValue = todaySyncValue(state.monthly)
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = AppSpacing.smallGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        TodayLedgerHeader(ledgerName = ledgerName, ledgerRole = state.ledgerRole)
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.soft))
        TodayMonthSummary(stats = state.monthly.stats, syncValue = syncValue)
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
private fun TodayMonthSummary(stats: MonthlyStats?, syncValue: String) {
    val currencyDisplay = LocalCurrencyDisplay.current
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
    ) {
        Text(
            text = stringResource(R.string.today_month_spend_label),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelMedium,
        )
        Text(
            text = stats?.totalAmountCents?.let { formatDisplayAmount(it, currencyDisplay) }
                ?: stringResource(R.string.today_month_empty_value),
            modifier = Modifier.fillMaxWidth(),
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.titleLarge.asAmount(AppAmountRole.Hero),
            autoSize = TextAutoSize.StepBased(
                minFontSize = 18.sp,
                maxFontSize = AppAmountRole.Hero.role.size,
                stepSize = 1.sp,
            ),
            maxLines = 1,
            overflow = TextOverflow.Clip,
        )
        Text(
            text = stringResource(R.string.today_month_count_with_status, stats?.count ?: 0, syncValue),
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
    val action = todayNextAction(
        pendingCount = state.pendingCount,
        missingAmountCount = state.missingAmountCount,
        duplicateCount = state.duplicateCount,
        readyToConfirmCount = state.readyToConfirmCount,
        readOnly = state.pending.readOnly,
    )
    val copy = todayNextActionCopy(action, state)
    val primaryIcon = if (action == TodayNextAction.UploadReceipt) {
        Icons.Filled.AddPhotoAlternate
    } else {
        Icons.AutoMirrored.Filled.KeyboardArrowRight
    }
    val primaryEnabled = action != TodayNextAction.UploadReceipt || (!state.pending.readOnly && !state.pending.uploading)
    val primaryClick = when (action) {
        TodayNextAction.UploadReceipt -> actions.onUploadReceipt
        TodayNextAction.OpenLedger -> actions.onOpenLedger
        else -> actions.onOpenPending
    }
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        TodayNextActionText(copy)
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            AppPrimaryButton(
                text = copy.buttonText,
                icon = primaryIcon,
                modifier = Modifier.weight(1f),
                enabled = primaryEnabled,
                onClick = primaryClick,
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
}

@Composable
private fun TodayNextActionText(copy: TodayNextActionCopy) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
        Text(
            text = stringResource(R.string.today_next_action_label),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelMedium,
        )
        Text(
            text = copy.title,
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.titleSmall,
            fontWeight = AppTextHierarchy.heading.weight,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            text = copy.caption,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun TodayWorkstream(
    state: TodayScreenState,
    onOpenPending: () -> Unit,
) {
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
            onClick = onOpenPending,
        )
        if (state.readyToConfirmCount > 0) {
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.24f))
            TodaySignalRow(
                label = stringResource(R.string.today_metric_ready),
                value = stringResource(R.string.today_count_receipts, state.readyToConfirmCount),
                onClick = onOpenPending,
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
private fun TodayMonthSignals(
    state: TodayScreenState,
    onOpenLedger: () -> Unit,
    onOpenInsights: () -> Unit,
) {
    val currencyDisplay = LocalCurrencyDisplay.current
    val topCategory = state.topCategory
    val recentUploadValue = state.monthly.lastUploadAt?.let(::displayTime)
        ?: stringResource(R.string.today_recent_upload_empty)
    val syncValue = todaySyncValue(state.monthly)
    TodaySignalSection(title = stringResource(R.string.today_section_month)) {
        TodaySignalRow(
            label = stringResource(R.string.today_metric_top_category),
            value = topCategory?.name ?: stringResource(R.string.today_top_category_empty),
            caption = topCategory?.amountCents?.let { formatDisplayAmount(it, currencyDisplay) },
            onClick = onOpenInsights,
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
                onClick = onOpenLedger,
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
private fun todaySyncValue(monthly: MonthlyStatsUiState): String = when {
    monthly.loading -> stringResource(R.string.today_sync_loading)
    monthly.statsLoadError != null -> stringResource(R.string.today_sync_error)
    monthly.statsSource == StatsSource.LocalFallback -> stringResource(R.string.today_sync_local)
    monthly.statsSource == StatsSource.Backend -> stringResource(R.string.today_sync_ready)
    else -> stringResource(R.string.today_sync_idle)
}

@Composable
private fun todayNextActionCopy(
    action: TodayNextAction,
    state: TodayScreenState,
): TodayNextActionCopy = when (action) {
    TodayNextAction.MissingAmount -> TodayNextActionCopy(
        title = stringResource(R.string.today_next_missing_amount_title),
        caption = stringResource(R.string.today_next_missing_amount_caption, state.missingAmountCount),
        buttonText = stringResource(R.string.today_next_review_button),
    )
    TodayNextAction.Duplicate -> TodayNextActionCopy(
        title = stringResource(R.string.today_next_duplicate_title),
        caption = stringResource(R.string.today_next_duplicate_caption, state.duplicateCount),
        buttonText = stringResource(R.string.today_next_review_button),
    )
    TodayNextAction.Ready -> TodayNextActionCopy(
        title = stringResource(R.string.today_next_ready_title),
        caption = stringResource(R.string.today_next_ready_caption, state.readyToConfirmCount),
        buttonText = stringResource(R.string.today_next_confirm_button),
    )
    TodayNextAction.ReviewPending -> TodayNextActionCopy(
        title = stringResource(R.string.today_next_review_title),
        caption = stringResource(R.string.today_next_review_caption, state.pendingCount),
        buttonText = stringResource(R.string.today_next_review_button),
    )
    TodayNextAction.UploadReceipt -> TodayNextActionCopy(
        title = stringResource(R.string.today_next_upload_title),
        caption = stringResource(R.string.today_next_upload_caption),
        buttonText = stringResource(R.string.today_next_upload_button),
    )
    TodayNextAction.OpenLedger -> TodayNextActionCopy(
        title = stringResource(R.string.today_next_ledger_title),
        caption = stringResource(R.string.today_next_ledger_caption, state.monthly.stats?.count ?: 0),
        buttonText = stringResource(R.string.today_next_ledger_button),
    )
}

internal fun todayNextAction(
    pendingCount: Int,
    missingAmountCount: Int,
    duplicateCount: Int,
    readyToConfirmCount: Int,
    readOnly: Boolean,
): TodayNextAction = when {
    readOnly && pendingCount > 0 -> TodayNextAction.ReviewPending
    readOnly -> TodayNextAction.OpenLedger
    missingAmountCount > 0 -> TodayNextAction.MissingAmount
    duplicateCount > 0 -> TodayNextAction.Duplicate
    readyToConfirmCount > 0 -> TodayNextAction.Ready
    pendingCount > 0 -> TodayNextAction.ReviewPending
    else -> TodayNextAction.UploadReceipt
}

internal object TodayRefreshIndicator {
    fun isActive(
        pendingLoading: Boolean,
        pendingLoadedOnce: Boolean,
        monthlyLoading: Boolean,
    ): Boolean = monthlyLoading || (pendingLoading && !pendingLoadedOnce)
}
