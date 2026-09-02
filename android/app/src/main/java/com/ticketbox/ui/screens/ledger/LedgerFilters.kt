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
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.HorizontalDivider
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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.shiftLedgerMonth
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.ui.components.AppOutlinedButtonOptions
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.screens.LedgerRecordCtaSlot
import com.ticketbox.viewmodel.LedgerUiState
import com.ticketbox.viewmodel.LedgerDataQualityFilter

private object LedgerFilterLayout {
    val CompactIconSize = 16.dp
    val StepIconSize = 20.dp
    val InlineIconSize = 18.dp
    val ToolMinimumWidth = 84.dp
}

@Composable
internal fun LedgerFilterPanel(
    state: LedgerUiState,
    actions: LedgerFilterPanelActions,
    recordCtaSlot: LedgerRecordCtaSlot?,
    showSummaryHeader: Boolean = true,
) {
    // W2-B: 去卡中卡——头部节奏直接落在页面上，不再套 AppContentCard。
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        if (showSummaryHeader) {
            LedgerHeader(
                state = state,
            )
            HorizontalDivider(
                color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium),
            )
        }
        LedgerInlineFilters(
            state = state,
            recordCtaSlot = recordCtaSlot,
            // 支撑 pane（无 summary 头）是窄控制面，使用分行布局；主头部整宽用双行。
            narrowControls = !showSummaryHeader,
            actions = actions,
        )
    }
}

internal data class LedgerFilterPanelActions(
    val onOpenMonthPicker: () -> Unit,
    val onOpenTools: () -> Unit,
    val onOpenSearch: () -> Unit,
    val onManualAdd: () -> Unit,
    val onMonthChange: (String) -> Unit,
)

@Composable
private fun LedgerInlineFilters(
    state: LedgerUiState,
    recordCtaSlot: LedgerRecordCtaSlot?,
    narrowControls: Boolean,
    actions: LedgerFilterPanelActions,
) {
    val activeFilterCount = ledgerActiveFilterCount(state)
    // Prev/next only when a concrete month is selected; "全部月份" has no neighbor.
    val previousMonth = remember(state.monthFilter) { shiftLedgerMonth(state.monthFilter, -1L) }
    val nextMonth = remember(state.monthFilter) { shiftLedgerMonth(state.monthFilter, 1L) }
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        if (narrowControls) {
            // 窄控制 pane：月份导航独占一行，标签必须可读；搜索/工具与筛选同行，
            // 记一笔整行。禁止把宽度竞争转嫁成月份或箭头的挤压。
            LedgerMonthStepper(
                state = LedgerMonthStepperState(
                    label = compactLedgerMonthLabel(state.monthFilter).takeIf { state.monthFilter.isNotBlank() }
                        ?: stringResource(R.string.ledger_inline_month_all),
                    previousMonth = previousMonth,
                    nextMonth = nextMonth,
                ),
                actions = LedgerMonthStepperActions(
                    onOpenMonthPicker = actions.onOpenMonthPicker,
                    onMonthChange = actions.onMonthChange,
                ),
                modifier = Modifier.fillMaxWidth(),
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                LedgerFilterToolButton(
                    onClick = actions.onOpenTools,
                    label = ledgerInlineFilterLabel(state, activeFilterCount),
                    selected = activeFilterCount > 0,
                    modifier = Modifier.weight(1f),
                )
                // W2-B: 搜索提为头部一级入口；「工具」文字链接退役为图标入口。
                LedgerChromeIconButton(
                    icon = Icons.Filled.Search,
                    description = stringResource(R.string.global_search_header_title),
                    onClick = actions.onOpenSearch,
                )
                LedgerChromeIconButton(
                    icon = Icons.Filled.Tune,
                    description = stringResource(R.string.ledger_tools_title),
                    onClick = actions.onOpenTools,
                )
            }
            // 单一记一笔槽位：仅 Header 槽在此渲染；空态槽由空态卡承担，Viewer 无入口。
            if (recordCtaSlot == LedgerRecordCtaSlot.Header) {
                LedgerRecordButton(
                    onClick = actions.onManualAdd,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        } else {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                LedgerMonthStepper(
                    state = LedgerMonthStepperState(
                        label = compactLedgerMonthLabel(state.monthFilter).takeIf { state.monthFilter.isNotBlank() }
                            ?: stringResource(R.string.ledger_inline_month_all),
                        previousMonth = previousMonth,
                        nextMonth = nextMonth,
                    ),
                    actions = LedgerMonthStepperActions(
                        onOpenMonthPicker = actions.onOpenMonthPicker,
                        onMonthChange = actions.onMonthChange,
                    ),
                    modifier = Modifier.weight(1f),
                )
                // W2-B: 搜索提为头部一级入口；「工具」文字链接退役为图标入口。
                LedgerChromeIconButton(
                    icon = Icons.Filled.Search,
                    description = stringResource(R.string.global_search_header_title),
                    onClick = actions.onOpenSearch,
                )
                LedgerChromeIconButton(
                    icon = Icons.Filled.Tune,
                    description = stringResource(R.string.ledger_tools_title),
                    onClick = actions.onOpenTools,
                )
            }
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                LedgerFilterToolButton(
                    onClick = actions.onOpenTools,
                    label = ledgerInlineFilterLabel(state, activeFilterCount),
                    selected = activeFilterCount > 0,
                    modifier = Modifier.weight(1f),
                )
                // 单一记一笔槽位：仅 Header 槽在此渲染；空态槽由空态卡承担，Viewer 无入口。
                if (recordCtaSlot == LedgerRecordCtaSlot.Header) {
                    LedgerRecordButton(
                        onClick = actions.onManualAdd,
                        modifier = Modifier.weight(1f),
                    )
                }
            }
        }
    }
}

@Composable
private fun LedgerRecordButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Button(
        onClick = onClick,
        modifier = modifier.heightIn(min = AppSpacing.controlMinHeight),
        shape = RoundedCornerShape(AppRadius.extraSmall),
        contentPadding = PaddingValues(horizontal = AppSpacing.smallGap),
        colors = ButtonDefaults.buttonColors(
            containerColor = MaterialTheme.colorScheme.primary,
            contentColor = MaterialTheme.colorScheme.onPrimary,
        ),
    ) {
        Icon(
            imageVector = Icons.Filled.Add,
            contentDescription = null,
            modifier = Modifier.size(LedgerFilterLayout.CompactIconSize),
        )
        Text(
            text = stringResource(R.string.ledger_header_add_button),
            modifier = Modifier.padding(start = AppSpacing.miniGap),
            style = MaterialTheme.typography.labelLarge,
            maxLines = 1,
        )
    }
}

@Composable
private fun compactLedgerMonthLabel(monthFilter: String): String {
    val parts = monthFilter.split("-")
    return if (parts.size == 2 && parts[0].length == 4 && parts[1].length == 2) {
        "${parts[0]}.${parts[1]}"
    } else {
        displayMonthLabel(monthFilter)
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
        state.dataQualityFilter == LedgerDataQualityFilter.MissingCategory ->
            stringResource(R.string.ledger_inline_filter_missing_category)
        state.dataQualityFilter == LedgerDataQualityFilter.ConfirmedWithoutImage ->
            stringResource(R.string.ledger_inline_filter_confirmed_without_image)
        else -> stringResource(R.string.ledger_inline_searched)
    }
}

private fun ledgerActiveFilterCount(state: LedgerUiState): Int {
    var count = 0
    if (state.categoryFilter.isNotBlank()) count += 1
    if (state.tagFilter.isNotBlank()) count += 1
    if (state.query.isNotBlank()) count += 1
    if (state.dataQualityFilter != null) count += 1
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
            .heightIn(min = AppSpacing.controlMinHeight)
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
                modifier = Modifier.weight(1f),
                textAlign = TextAlign.Center,
            )
            Icon(
                imageVector = Icons.Filled.ExpandMore,
                contentDescription = stringResource(R.string.ledger_inline_month_picker_description),
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.size(LedgerFilterLayout.CompactIconSize),
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
            .size(AppSpacing.controlMinHeight)
            .alpha(if (enabled) 1f else 0.36f)
            .clip(RoundedCornerShape(AppRadius.extraSmall))
            .clickable(enabled = enabled, role = Role.Button, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            imageVector = icon,
            contentDescription = description,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(LedgerFilterLayout.StepIconSize),
        )
    }
}

@Composable
private fun LedgerChromeIconButton(
    icon: ImageVector,
    description: String,
    onClick: () -> Unit,
) {
    Box(
        modifier = Modifier
            .size(AppSpacing.controlMinHeight)
            .clip(RoundedCornerShape(AppRadius.extraSmall))
            .clickable(role = Role.Button, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            imageVector = icon,
            contentDescription = description,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(LedgerFilterLayout.StepIconSize),
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
            .heightIn(min = AppSpacing.controlMinHeight)
            .widthIn(min = LedgerFilterLayout.ToolMinimumWidth)
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
                modifier = Modifier.size(LedgerFilterLayout.CompactIconSize),
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
            contentPadding = PaddingValues(
                horizontal = AppSpacing.compactPadding,
                vertical = AppSpacing.none,
            ),
        ),
    ) {
        if (icon != null) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                modifier = Modifier.size(LedgerFilterLayout.InlineIconSize),
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
