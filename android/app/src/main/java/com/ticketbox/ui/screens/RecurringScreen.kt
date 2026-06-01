package com.ticketbox.ui.screens

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.RecurringCandidate
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.ListItemSkeleton
import com.ticketbox.ui.components.SafeBadge
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.viewmodel.RecurringUiState
import com.valentinilk.shimmer.shimmer

private enum class RecurringTab(val label: String) {
    Upcoming("即将"),
    Active("活跃"),
    Paused("暂停"),
}

@Composable
fun RecurringScreen(
    state: RecurringUiState,
    onRefresh: () -> Unit,
    onConfirmCandidate: (RecurringCandidate) -> Unit,
    onPause: (String, String) -> Unit,
    onResume: (String, String) -> Unit,
    onArchive: (String) -> Unit,
    onBack: (() -> Unit)? = null,
) {
    val currencyDisplay = LocalCurrencyDisplay.current

    BackHandler(enabled = onBack != null) {
        onBack?.invoke()
    }

    var selectedTab by rememberSaveable { mutableStateOf(RecurringTab.Upcoming) }
    val activeItems = state.items.filter { it.status == "active" }
    val visibleItems = when (selectedTab) {
        RecurringTab.Upcoming -> activeItems.sortedWith(compareBy<RecurringItem> { it.nextExpectedDate ?: "9999-99-99" }.thenBy { it.merchant })
        RecurringTab.Active -> activeItems.sortedBy { it.merchant }
        RecurringTab.Paused -> state.items.filter { it.status == "paused" }.sortedBy { it.merchant }
    }

    AppScrollableContent(
        role = AppPageRole.Stats,
        isRefreshing = state.loading,
        onRefresh = onRefresh,
        hasBottomBar = onBack == null,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
    ) {
        item {
            Column(
                verticalArrangement = Arrangement.spacedBy(
                    if (onBack == null) AppSpacing.compactGap else AppSpacing.smallGap,
                ),
            ) {
                onBack?.let {
                    TextButton(onClick = it) {
                        Icon(
                            Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "返回统计",
                            modifier = Modifier.size(18.dp),
                        )
                        Spacer(Modifier.width(4.dp))
                        Text("返回统计")
                    }
                }
                AppPageHeader(
                    title = "固定支出",
                    subtitle = "候选需手动确认；正式记录只做提醒和对比，不会自动入账。",
                ) {
                    SafeBadge()
                }
                RecurringTabRow(
                    selected = selectedTab,
                    onSelect = { selectedTab = it },
                    activeCount = activeItems.size,
                    pausedCount = state.items.count { it.status == "paused" },
                )
            }
        }
        state.message?.let {
            item { Text(it, color = MaterialTheme.colorScheme.secondary) }
        }
        item {
            RecurringItemsCard(
                title = selectedTab.label,
                items = visibleItems,
                loading = state.loading,
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
                loading = state.loading,
                currencyDisplay = currencyDisplay,
                canModify = state.canModify,
                onConfirmCandidate = onConfirmCandidate,
            )
        }
    }
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
            FilterChip(
                selected = selected == tab,
                onClick = { onSelect(tab) },
                label = { Text("${tab.label} $count") },
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
    onPause: (String, String) -> Unit,
    onResume: (String, String) -> Unit,
    onArchive: (String) -> Unit,
) {
    val visuals = LocalThemeVisuals.current
    AppGlassCard(containerAlpha = 0.94f) {
        Column(
            modifier = Modifier.padding(AppSpacing.cardPaddingSmall),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = "$title 固定支出",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = AppTextHierarchy.heading.weight,
                )
                Text(
                    text = "${items.size} 项",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelMedium,
                )
            }
            if (items.isEmpty()) {
                if (loading) {
                    Column(modifier = Modifier.shimmer()) {
                        repeat(4) { ListItemSkeleton(horizontalPadding = 0.dp) }
                    }
                } else {
                    Text(
                        text = "还没有这一类固定支出。",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodyMedium,
                    )
                }
            } else {
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
    onPause: (String, String) -> Unit,
    onResume: (String, String) -> Unit,
    onArchive: (String) -> Unit,
) {
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
                    text = item.merchant.ifBlank { "未填写商家" },
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
                style = MaterialTheme.typography.titleSmall,
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
                        label = { Text("本月偏高 ${item.amountDeltaPercent ?: 0}%") },
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
    onPause: (String, String) -> Unit,
    onResume: (String, String) -> Unit,
    onArchive: (String) -> Unit,
) {
    Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
        when (item.status) {
            "active" -> TextButton(onClick = { onPause(item.publicId, item.updatedAt) }) { Text("暂停") }
            "paused" -> TextButton(onClick = { onResume(item.publicId, item.updatedAt) }) { Text("恢复") }
        }
        TextButton(onClick = { onArchive(item.publicId) }) {
            Icon(Icons.Filled.DeleteOutline, contentDescription = "归档固定支出")
            Text("归档")
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
    AppGlassCard(containerAlpha = 0.94f) {
        Column(
            modifier = Modifier.padding(AppSpacing.cardPaddingSmall),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        ) {
            Text(
                text = "固定支出候选（未确认）",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = AppTextHierarchy.heading.weight,
            )
            Text(
                text = "根据最近账单识别，仅供参考，不会自动入账；确认后才进入正式固定支出。",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
            if (candidates.isEmpty()) {
                if (loading) {
                    Column(modifier = Modifier.shimmer()) {
                        repeat(3) { ListItemSkeleton(horizontalPadding = 0.dp) }
                    }
                } else {
                    Text(
                        text = "暂无新的固定支出候选。",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodyMedium,
                    )
                }
            } else {
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
                text = candidate.merchant.ifBlank { "未填写商家" },
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = FontWeight.SemiBold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = "${formatDisplayAmount(candidate.amountCents, currencyDisplay)} · ${candidate.occurrenceCount} 次 · ${candidate.confidence}",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        if (canModify) {
            Button(onClick = { onConfirmCandidate(candidate) }) {
                Icon(Icons.Filled.Add, contentDescription = "确认固定支出候选")
                Text("确认")
            }
        }
    }
}

@Composable
private fun StatusChip(status: String) {
    val visuals = LocalThemeVisuals.current
    val label = when (status) {
        "active" -> "活跃"
        "paused" -> "暂停"
        "archived" -> "归档"
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

private fun recurringMeta(item: RecurringItem, currencyDisplay: CurrencyDisplay): String {
    val next = item.nextExpectedDate?.let { "下次 $it" } ?: "下次未估算"
    val count = "${item.occurrenceCount} 次"
    val anomaly = if (item.anomalyStatus == "higher_than_average") {
        " · 本月 ${formatDisplayAmount(item.currentMonthAmountCents, currencyDisplay)}"
    } else {
        ""
    }
    return "$next · $count$anomaly"
}
