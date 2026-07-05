package com.ticketbox.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.annotation.StringRes
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.RecurringCandidate
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppListStateContent
import com.ticketbox.ui.components.AppListStateSpec
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryPageSlots
import com.ticketbox.ui.components.AppSecondaryRefreshState
import com.ticketbox.ui.components.AppSecondaryScrollableContent
import com.ticketbox.ui.components.AppSectionGroup
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.StatusPill
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.viewmodel.RecurringUiState

private enum class RecurringTab(@param:StringRes val labelRes: Int) {
    Upcoming(R.string.recurring_tab_upcoming),
    Active(R.string.recurring_tab_active),
    Paused(R.string.recurring_tab_paused),
}

@Composable
fun RecurringScreen(
    state: RecurringUiState,
    onRefresh: () -> Unit,
    onConfirmCandidate: (RecurringCandidate) -> Unit,
    onPause: (String, Long) -> Unit,
    onResume: (String, Long) -> Unit,
    onArchive: (String) -> Unit,
    onBack: (() -> Unit)? = null,
) {
    val currencyDisplay = LocalCurrencyDisplay.current

    var selectedTab by rememberSaveable { mutableStateOf(RecurringTab.Upcoming) }
    val activeItems = state.items.filter { it.status == "active" }
    val visibleItems = when (selectedTab) {
        RecurringTab.Upcoming -> activeItems.sortedWith(compareBy<RecurringItem> { it.nextExpectedDate ?: "9999-99-99" }.thenBy { it.merchant })
        RecurringTab.Active -> activeItems.sortedBy { it.merchant }
        RecurringTab.Paused -> state.items.filter { it.status == "paused" }.sortedBy { it.merchant }
    }
    val hasReadableData = state.items.isNotEmpty() || state.candidates.isNotEmpty()

    AppSecondaryScrollableContent(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Stats,
            title = stringResource(R.string.recurring_header_title),
            subtitle = stringResource(R.string.recurring_header_subtitle),
            backText = stringResource(R.string.recurring_back_to_stats),
            onBack = onBack,
            hasBottomBar = onBack == null,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
        ),
        refresh = AppSecondaryRefreshState(
            isRefreshing = ReadableRefreshIndicator.isActive(
                loading = state.loading,
                hasReadableData = hasReadableData,
            ),
            onRefresh = onRefresh,
        ),
        slots = AppSecondaryPageSlots(
            actions = {
                RecurringStatusBadge(
                    state = state,
                    activeCount = activeItems.size,
                    pausedCount = state.items.count { it.status == "paused" },
                    hasReadableData = hasReadableData,
                )
            },
        ),
    ) {
        item {
            RecurringTabRow(
                selected = selectedTab,
                onSelect = { selectedTab = it },
                activeCount = activeItems.size,
                pausedCount = state.items.count { it.status == "paused" },
            )
        }
        state.message?.let {
            item { AppStatusBanner(message = it, tone = state.messageTone) }
        }
        item {
            RecurringItemsCard(
                title = stringResource(selectedTab.labelRes),
                items = visibleItems,
                loading = state.loading && state.items.isEmpty(),
                currencyDisplay = currencyDisplay,
                canModify = state.canModify,
                onPause = onPause,
                onResume = onResume,
                onArchive = onArchive,
            )
        }
        item {
            RecurringCandidatesCard(
                candidates = state.candidates,
                loading = state.loading && state.candidates.isEmpty(),
                currencyDisplay = currencyDisplay,
                canModify = state.canModify,
                onConfirmCandidate = onConfirmCandidate,
            )
        }
    }
}

@Composable
private fun RecurringStatusBadge(
    state: RecurringUiState,
    activeCount: Int,
    pausedCount: Int,
    hasReadableData: Boolean,
) {
    val tones = LocalStateTokens.current
    val (text, tone) = when {
        state.loading && !hasReadableData -> stringResource(R.string.recurring_badge_loading) to tones.info
        state.message != null && !hasReadableData -> stringResource(R.string.recurring_badge_refresh_needed) to tones.warn
        !state.canModify -> stringResource(R.string.recurring_badge_readonly) to tones.warn
        state.candidates.isNotEmpty() -> stringResource(R.string.recurring_badge_candidates, state.candidates.size) to tones.info
        activeCount > 0 -> stringResource(R.string.recurring_badge_active, activeCount) to tones.success
        pausedCount > 0 -> stringResource(R.string.recurring_badge_paused, pausedCount) to tones.info
        else -> stringResource(R.string.recurring_badge_empty) to tones.neutral
    }
    StatusPill(text = text, tone = tone)
}

@Composable
private fun RecurringTabRow(
    selected: RecurringTab,
    onSelect: (RecurringTab) -> Unit,
    activeCount: Int,
    pausedCount: Int,
) {
    Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        RecurringTab.entries.forEach { tab ->
            val count = when (tab) {
                RecurringTab.Upcoming,
                RecurringTab.Active -> activeCount
                RecurringTab.Paused -> pausedCount
            }
            AppFilterChip(
                selected = selected == tab,
                onClick = { onSelect(tab) },
                label = stringResource(R.string.recurring_tab_label_count, stringResource(tab.labelRes), count),
            )
        }
    }
}

@Composable
private fun RecurringItemsCard(
    title: String,
    items: List<RecurringItem>,
    loading: Boolean,
    currencyDisplay: CurrencyDisplay,
    canModify: Boolean,
    onPause: (String, Long) -> Unit,
    onResume: (String, Long) -> Unit,
    onArchive: (String) -> Unit,
) {
    val visuals = LocalThemeVisuals.current
    AppSectionGroup(
        contentPadding = PaddingValues(vertical = AppSpacing.contentGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        Column(
            verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = stringResource(R.string.recurring_items_card_title, title),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = AppTextHierarchy.heading.weight,
                )
                Text(
                    text = stringResource(R.string.recurring_items_card_count, items.size),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelMedium,
                )
            }
            AppListStateContent(
                state = AppListStateSpec(
                    isEmpty = items.isEmpty(),
                    loading = loading,
                    emptyText = stringResource(R.string.recurring_items_empty),
                    skeletonRows = 4,
                ),
            ) {
                items.forEachIndexed { index, item ->
                    if (index > 0) HorizontalDivider(color = visuals.chipUnselected.copy(alpha = 0.72f))
                    RecurringItemRow(
                        item = item,
                        currencyDisplay = currencyDisplay,
                        canModify = canModify,
                        onPause = onPause,
                        onResume = onResume,
                        onArchive = onArchive,
                    )
                }
            }
        }
    }
}

@Composable
private fun RecurringItemRow(
    item: RecurringItem,
    currencyDisplay: CurrencyDisplay,
    canModify: Boolean,
    onPause: (String, Long) -> Unit,
    onResume: (String, Long) -> Unit,
    onArchive: (String) -> Unit,
) {
    val merchantFallback = stringResource(R.string.recurring_item_merchant_fallback)
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(
                modifier = Modifier
                    .weight(1f)
                    .padding(end = AppSpacing.contentGap),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
            ) {
                Text(
                    text = item.merchant.ifBlank { merchantFallback },
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    text = recurringMeta(item, currencyDisplay),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Text(
                text = formatDisplayAmount(item.lastAmountCents, currencyDisplay),
                style = MaterialTheme.typography.titleSmall.tabularNum(),
                fontWeight = AppTextHierarchy.body.weight,
            )
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                StatusChip(item.status)
                if (item.anomalyStatus == "higher_than_average") {
                    AssistChip(
                        onClick = {},
                        label = { Text(stringResource(R.string.recurring_item_anomaly_higher, item.amountDeltaPercent ?: 0)) },
                    )
                }
            }
            if (canModify) {
                RecurringActions(item, onPause, onResume, onArchive)
            }
        }
    }
}

@Composable
private fun RecurringActions(
    item: RecurringItem,
    onPause: (String, Long) -> Unit,
    onResume: (String, Long) -> Unit,
    onArchive: (String) -> Unit,
) {
    Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
        when (item.status) {
            "active" -> TextButton(onClick = { onPause(item.publicId, item.rowVersion) }) {
                Text(stringResource(R.string.recurring_action_pause))
            }
            "paused" -> TextButton(onClick = { onResume(item.publicId, item.rowVersion) }) {
                Text(stringResource(R.string.recurring_action_resume))
            }
        }
        TextButton(onClick = { onArchive(item.publicId) }) {
            Icon(Icons.Filled.DeleteOutline, contentDescription = stringResource(R.string.recurring_action_archive_description))
            Text(stringResource(R.string.recurring_action_archive))
        }
    }
}

@Composable
private fun RecurringCandidatesCard(
    candidates: List<RecurringCandidate>,
    loading: Boolean,
    currencyDisplay: CurrencyDisplay,
    canModify: Boolean,
    onConfirmCandidate: (RecurringCandidate) -> Unit,
) {
    AppSectionGroup(
        contentPadding = PaddingValues(vertical = AppSpacing.contentGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        showTopDivider = false,
    ) {
        Column(
            verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        ) {
            Text(
                text = stringResource(R.string.recurring_candidates_card_title),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = AppTextHierarchy.heading.weight,
            )
            Text(
                text = stringResource(R.string.recurring_candidates_card_subtitle),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
            AppListStateContent(
                state = AppListStateSpec(
                    isEmpty = candidates.isEmpty(),
                    loading = loading,
                    emptyText = stringResource(R.string.recurring_candidates_empty),
                ),
            ) {
                candidates.take(8).forEach { candidate ->
                    CandidateRow(candidate, currencyDisplay, canModify, onConfirmCandidate)
                }
            }
        }
    }
}

@Composable
private fun CandidateRow(
    candidate: RecurringCandidate,
    currencyDisplay: CurrencyDisplay,
    canModify: Boolean,
    onConfirmCandidate: (RecurringCandidate) -> Unit,
) {
    val merchantFallback = stringResource(R.string.recurring_candidate_merchant_fallback)
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(
            modifier = Modifier
                .weight(1f)
                .padding(end = AppSpacing.contentGap),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
        ) {
            Text(
                text = candidate.merchant.ifBlank { merchantFallback },
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = FontWeight.SemiBold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = stringResource(
                    R.string.recurring_candidate_meta,
                    formatDisplayAmount(candidate.amountCents, currencyDisplay),
                    candidate.occurrenceCount,
                    candidate.confidence,
                ),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall.tabularNum(),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        if (canModify) {
            Button(onClick = { onConfirmCandidate(candidate) }) {
                Icon(Icons.Filled.Add, contentDescription = stringResource(R.string.recurring_candidate_confirm_description))
                Text(stringResource(R.string.recurring_candidate_confirm))
            }
        }
    }
}

@Composable
private fun StatusChip(status: String) {
    val visuals = LocalThemeVisuals.current
    val label = when (status) {
        "active" -> stringResource(R.string.recurring_status_active)
        "paused" -> stringResource(R.string.recurring_status_paused)
        "archived" -> stringResource(R.string.recurring_status_archived)
        else -> status
    }
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(AppRadius.pill))
            .background(visuals.chipSelected.copy(alpha = if (status == "active") 0.95f else 0.58f))
            .padding(horizontal = AppSpacing.smallGap, vertical = AppSpacing.tinyGap + 1.dp),
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            fontWeight = FontWeight.SemiBold,
        )
    }
}

@Composable
private fun recurringMeta(item: RecurringItem, currencyDisplay: CurrencyDisplay): String {
    val next = item.nextExpectedDate?.let { stringResource(R.string.recurring_meta_next, it) }
        ?: stringResource(R.string.recurring_meta_next_unknown)
    val count = stringResource(R.string.recurring_meta_count, item.occurrenceCount)
    val anomaly = if (item.anomalyStatus == "higher_than_average") {
        stringResource(
            R.string.recurring_meta_anomaly_current_amount,
            formatDisplayAmount(item.currentMonthAmountCents, currencyDisplay),
        )
    } else {
        ""
    }
    return stringResource(R.string.recurring_meta_combined, next, count, anomaly)
}
