package com.ticketbox.ui.screens.ledger

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowLeft
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.ui.components.AppOutlinedButtonOptions
import com.ticketbox.ui.components.AppAdaptiveEqualControlRow
import com.ticketbox.domain.model.shiftLedgerMonth
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalThemeVisuals
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
    AppAdaptiveEqualControlRow(
        leading = { controlModifier ->
            LedgerMonthStepper(
                state = LedgerMonthStepperState(
                    label = displayMonthLabel(state.monthFilter).takeIf { state.monthFilter.isNotBlank() }
                        ?: stringResource(R.string.ledger_inline_month_all),
                    previousMonth = previousMonth,
                    nextMonth = nextMonth,
                ),
                actions = LedgerMonthStepperActions(
                    onOpenMonthPicker = onOpenMonthPicker,
                    onMonthChange = onMonthChange,
                ),
                modifier = controlModifier,
            )
        },
        trailing = { controlModifier ->
            LedgerFilterToolButton(
                onClick = onOpenTools,
                label = ledgerInlineFilterLabel(state, activeFilterCount),
                selected = activeFilterCount > 0,
                modifier = controlModifier,
            )
        },
    )
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

@Immutable
private data class LedgerMonthStepperState(
    val label: String,
    val previousMonth: String?,
    val nextMonth: String?,
)

private data class LedgerMonthStepperActions(
    val onOpenMonthPicker: () -> Unit,
    val onMonthChange: (String) -> Unit,
)

@Composable
private fun LedgerMonthStepper(
    state: LedgerMonthStepperState,
    actions: LedgerMonthStepperActions,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .heightIn(min = 40.dp)
            .padding(vertical = AppSpacing.tinyGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        LedgerMonthStepButton(
            icon = Icons.AutoMirrored.Filled.KeyboardArrowLeft,
            description = stringResource(R.string.ledger_inline_month_prev),
            enabled = state.previousMonth != null,
            onClick = { state.previousMonth?.let(actions.onMonthChange) },
        )
        Row(
            modifier = Modifier
                .weight(1f)
                .clip(RoundedCornerShape(AppRadius.extraSmall))
                .clickable(role = Role.Button, onClick = actions.onOpenMonthPicker)
                .padding(horizontal = AppSpacing.smallGap, vertical = AppSpacing.smallGap),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.miniGap, Alignment.CenterHorizontally),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = state.label,
                color = MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.labelLarge,
                fontWeight = AppTextHierarchy.heading.weight,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Icon(
                imageVector = Icons.Filled.ExpandMore,
                contentDescription = stringResource(R.string.ledger_inline_month_picker_description),
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.size(16.dp),
            )
        }
        LedgerMonthStepButton(
            icon = Icons.AutoMirrored.Filled.KeyboardArrowRight,
            description = stringResource(R.string.ledger_inline_month_next),
            enabled = state.nextMonth != null,
            onClick = { state.nextMonth?.let(actions.onMonthChange) },
        )
    }
}

@Composable
private fun LedgerMonthStepButton(
    icon: ImageVector,
    description: String,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    Box(
        modifier = Modifier
            .size(32.dp)
            .alpha(if (enabled) 1f else 0.36f)
            .clip(RoundedCornerShape(AppRadius.extraSmall))
            .clickable(enabled = enabled, role = Role.Button, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            imageVector = icon,
            contentDescription = description,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(20.dp),
        )
    }
}

@Composable
private fun LedgerFilterToolButton(
    label: String,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val visuals = LocalThemeVisuals.current
    val shape = RoundedCornerShape(AppRadius.extraSmall)
    val labelColor = if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant
    Row(
        modifier = modifier
            .heightIn(min = 40.dp)
            .widthIn(min = 84.dp)
            .clip(shape)
            .then(
                if (selected) {
                    Modifier.background(visuals.chipSelected.copy(alpha = AppAlpha.medium))
                } else {
                    Modifier
                },
            )
            .clickable(role = Role.Button, onClick = onClick)
            .padding(horizontal = AppSpacing.smallGap, vertical = AppSpacing.smallGap),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.miniGap, Alignment.CenterHorizontally),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (selected) {
            Icon(
                imageVector = Icons.Filled.Check,
                contentDescription = null,
                tint = labelColor,
                modifier = Modifier.size(16.dp),
            )
        }
        Text(
            text = label,
            color = labelColor,
            style = MaterialTheme.typography.labelLarge,
            fontWeight = if (selected) AppTextHierarchy.heading.weight else AppTextHierarchy.body.weight,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
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
        onClick = onClick,
        options = AppOutlinedButtonOptions(
            enabled = enabled,
            contentPadding = PaddingValues(horizontal = AppSpacing.compactPadding, vertical = 0.dp),
        ),
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
