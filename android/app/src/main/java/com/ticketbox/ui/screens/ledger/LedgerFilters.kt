package com.ticketbox.ui.screens.ledger

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowLeft
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.domain.model.shiftLedgerMonth
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.LedgerUiState

@Composable
internal fun LedgerFilterPanel(
    state: LedgerUiState,
    onOpenMonthPicker: () -> Unit,
    onOpenTools: () -> Unit,
    onManualAdd: () -> Unit,
    onMonthChange: (String) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.compactPadding)) {
        // 三段竖向布局：账本头（含状态 pill + KPI）→ 视图模式段 → 内联 chip 筛选。
        // 之前在最末又渲染了一段 `ledgerCombinedStatusLine` 文本——它把 LedgerHeader
        // 的状态 pill 和 LedgerInlineFilters 的 chip 状态又重新文字叙述一遍，纯冗余。
        // 移除后顶部垂直高度减少 ~24dp，信息密度更高且没有损失任何用户能用上的信息。
        LedgerHeader(state = state, onManualAdd = onManualAdd)
        LedgerInlineFilters(
            state = state,
            onOpenMonthPicker = onOpenMonthPicker,
            onOpenTools = onOpenTools,
            onMonthChange = onMonthChange,
        )
    }
}

@Composable
private fun LedgerInlineFilters(
    state: LedgerUiState,
    onOpenMonthPicker: () -> Unit,
    onOpenTools: () -> Unit,
    onMonthChange: (String) -> Unit,
) {
    val activeFilterCount = ledgerActiveFilterCount(state)
    // Prev/next only when a concrete month is selected; "全部月份" has no neighbor.
    val previousMonth = remember(state.monthFilter) { shiftLedgerMonth(state.monthFilter, -1L) }
    val nextMonth = remember(state.monthFilter) { shiftLedgerMonth(state.monthFilter, 1L) }
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (previousMonth != null) {
            LedgerMonthArrowChip(
                icon = Icons.AutoMirrored.Filled.KeyboardArrowLeft,
                description = stringResource(R.string.ledger_inline_month_prev),
                onClick = { onMonthChange(previousMonth) },
            )
        }
        AppFilterChip(
            selected = true,
            onClick = onOpenMonthPicker,
            label = displayMonthLabel(state.monthFilter).takeIf { state.monthFilter.isNotBlank() }
                ?: stringResource(R.string.ledger_inline_month_all),
            modifier = Modifier.weight(1f),
            trailingIcon = {
                Icon(
                    imageVector = Icons.Filled.ExpandMore,
                    contentDescription = stringResource(R.string.ledger_inline_month_picker_description),
                    modifier = Modifier.size(FilterChipDefaults.IconSize),
                )
            },
        )
        if (nextMonth != null) {
            LedgerMonthArrowChip(
                icon = Icons.AutoMirrored.Filled.KeyboardArrowRight,
                description = stringResource(R.string.ledger_inline_month_next),
                onClick = { onMonthChange(nextMonth) },
            )
        }
        AppFilterChip(
            selected = activeFilterCount > 0,
            onClick = onOpenTools,
            label = ledgerInlineFilterLabel(state, activeFilterCount),
            leadingIcon = if (activeFilterCount > 0) {
                {
                    Icon(
                        imageVector = Icons.Filled.Check,
                        contentDescription = null,
                        modifier = Modifier.size(FilterChipDefaults.IconSize),
                    )
                }
            } else {
                null
            },
        )
    }
}

@Composable
private fun ledgerInlineFilterLabel(
    state: LedgerUiState,
    activeFilterCount: Int,
): String {
    return when {
        activeFilterCount == 0 -> stringResource(R.string.ledger_inline_filter)
        activeFilterCount > 1 -> stringResource(R.string.ledger_inline_filter_count, activeFilterCount)
        state.categoryFilter.isNotBlank() -> state.categoryFilter
        state.tagFilter.isNotBlank() -> "#${state.tagFilter}"
        else -> stringResource(R.string.ledger_inline_searched)
    }
}

private fun ledgerActiveFilterCount(state: LedgerUiState): Int {
    var count = 0
    if (state.categoryFilter.isNotBlank()) count += 1
    if (state.tagFilter.isNotBlank()) count += 1
    if (state.query.isNotBlank()) count += 1
    return count
}

/**
 * Compact icon-only chip flanking the month chip for one-tap previous/next
 * month. Reuses [AppFilterChip] (so it stays visually in the chip row and on
 * the shared token palette); the [description] rides the icon for a11y since
 * the chip carries no visible label.
 */
@Composable
private fun LedgerMonthArrowChip(
    icon: ImageVector,
    description: String,
    onClick: () -> Unit,
) {
    AppFilterChip(
        selected = false,
        onClick = onClick,
        label = "",
        leadingIcon = {
            Icon(
                imageVector = icon,
                contentDescription = description,
                modifier = Modifier.size(FilterChipDefaults.IconSize),
            )
        },
    )
}

@Composable
internal fun LedgerInlineButton(
    text: String,
    modifier: Modifier,
    enabled: Boolean,
    onClick: () -> Unit,
    icon: ImageVector? = null,
) {
    AppOutlinedButton(
        modifier = modifier.heightIn(min = AppSpacing.controlMinHeight),
        enabled = enabled,
        onClick = onClick,
        contentPadding = PaddingValues(horizontal = AppSpacing.compactPadding, vertical = 0.dp),
    ) {
        if (icon != null) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                modifier = Modifier.size(18.dp),
            )
        }
        Text(
            text = text,
            modifier = if (icon == null) Modifier else Modifier.padding(start = AppSpacing.miniGap),
            maxLines = 1,
            softWrap = false,
            overflow = TextOverflow.Ellipsis,
        )
    }
}
