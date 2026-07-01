package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.onClick
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.DASHBOARD_CARD_BUDGET
import com.ticketbox.domain.model.DASHBOARD_CARD_GOALS
import com.ticketbox.domain.model.DASHBOARD_CARD_MONTHLY_SPEND
import com.ticketbox.domain.model.DASHBOARD_CARD_REPORTS
import com.ticketbox.domain.model.DashboardCard
import com.ticketbox.domain.model.StatsTab
import com.ticketbox.domain.model.statsDashboardKeysForTab
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStatsTokens
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.viewmodel.StatsUiState

internal data class StatsTopPanelActions(
    val onOpenMonthPicker: () -> Unit,
    val onTagChange: (String) -> Unit,
    val onTabChange: (StatsTab) -> Unit,
    val planning: StatsPlanningActions,
)

internal data class StatsPlanningActions(
    val onOpenBudget: () -> Unit,
    val onOpenRecurring: () -> Unit,
    val onOpenIncomePlans: () -> Unit,
    val onOpenDebtGoals: () -> Unit,
)

@Composable
internal fun StatsTopPanel(
    state: StatsUiState,
    selectedTab: StatsTab,
    visibleDashboardKeys: List<String>,
    actions: StatsTopPanelActions,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        AppPageHeader(
            title = stringResource(R.string.stats_header_title),
            action = {
                StatsPlanningMenu(actions.planning)
            },
        )
        StatsFilterRow(
            state = state,
            onOpenMonthPicker = actions.onOpenMonthPicker,
            onTagChange = actions.onTagChange,
        )
        StatsTabRow(
            selectedTab = selectedTab,
            dashboardCards = state.dashboardCards,
            visibleDashboardKeys = visibleDashboardKeys,
            tagFilterActive = state.selectedTag.isNotBlank(),
            onTabChange = actions.onTabChange,
        )
    }
}

@Composable
private fun StatsPlanningMenu(actions: StatsPlanningActions) {
    var menuOpen by remember { mutableStateOf(false) }
    Box {
        StatsPlanningMenuTrigger(
            expanded = menuOpen,
            onOpen = { menuOpen = true },
        )
        DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
            DropdownMenuItem(
                text = { Text(stringResource(R.string.stats_header_open_budget)) },
                onClick = { menuOpen = false; actions.onOpenBudget() },
            )
            DropdownMenuItem(
                text = { Text(stringResource(R.string.stats_header_open_recurring)) },
                onClick = { menuOpen = false; actions.onOpenRecurring() },
            )
            DropdownMenuItem(
                text = { Text(stringResource(R.string.stats_header_open_income_plans)) },
                onClick = { menuOpen = false; actions.onOpenIncomePlans() },
            )
            DropdownMenuItem(
                text = { Text(stringResource(R.string.stats_header_open_debt_goals)) },
                onClick = { menuOpen = false; actions.onOpenDebtGoals() },
            )
        }
    }
}

@Composable
private fun StatsPlanningMenuTrigger(
    expanded: Boolean,
    onOpen: () -> Unit,
) {
    val visuals = LocalThemeVisuals.current
    val controlTokens = LocalStatsTokens.current.control
    val menuDescription = stringResource(R.string.stats_header_menu_planning_description)
    val menuStateDescription = stringResource(
        if (expanded) {
            R.string.stats_header_menu_planning_expanded
        } else {
            R.string.stats_header_menu_planning_collapsed
        },
    )
    Box(
        modifier = Modifier
            .clearAndSetSemantics {
                contentDescription = menuDescription
                stateDescription = menuStateDescription
                role = Role.Button
                onClick(action = {
                    onOpen()
                    true
                })
            }
            .size(40.dp)
            .clip(RoundedCornerShape(AppRadius.pill))
            .background(visuals.chipSelected.copy(alpha = controlTokens.selectedAlpha))
            .border(
                width = 1.dp,
                color = MaterialTheme.colorScheme.primary.copy(alpha = controlTokens.borderAlpha),
                shape = RoundedCornerShape(AppRadius.pill),
            )
            .clickable(role = Role.Button, onClick = onOpen),
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            imageVector = Icons.Filled.Tune,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(20.dp),
        )
    }
}

@Composable
private fun StatsTabRow(
    selectedTab: StatsTab,
    dashboardCards: List<DashboardCard>,
    visibleDashboardKeys: List<String>,
    tagFilterActive: Boolean,
    onTabChange: (StatsTab) -> Unit,
) {
    LazyRow(horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap)) {
        items(StatsTab.entries, key = { it.name }) { tab ->
            StatsTextTab(
                label = statsTabLabel(tab, dashboardCards),
                selected = selectedTab == tab,
                enabled = statsDashboardKeysForTab(
                    tab,
                    visibleDashboardKeys,
                    tagFilterActive = tagFilterActive,
                ).isNotEmpty(),
                onClick = { onTabChange(tab) },
            )
        }
    }
}

@Composable
private fun statsTabLabel(
    tab: StatsTab,
    dashboardCards: List<DashboardCard>,
): String {
    val titleByKey = dashboardCards
        .filter { it.title.isNotBlank() }
        .associate { it.key to it.title }
    return when (tab) {
        StatsTab.Overview -> titleByKey[DASHBOARD_CARD_MONTHLY_SPEND] ?: stringResource(R.string.stats_tab_overview)
        StatsTab.Trend -> titleByKey[DASHBOARD_CARD_REPORTS] ?: stringResource(R.string.stats_tab_trend)
        StatsTab.Category -> stringResource(R.string.stats_tab_category)
        StatsTab.Budget -> titleByKey[DASHBOARD_CARD_BUDGET] ?: stringResource(R.string.stats_tab_budget)
        StatsTab.Goals -> titleByKey[DASHBOARD_CARD_GOALS] ?: stringResource(R.string.stats_tab_goals)
    }
}

@Composable
private fun StatsFilterRow(
    state: StatsUiState,
    onOpenMonthPicker: () -> Unit,
    onTagChange: (String) -> Unit,
) {
    val tags = (state.tags + state.stats?.byTag.orEmpty().map { it.tag })
        .map { it.trim() }
        .filter { it.isNotBlank() }
        .distinctBy { it.lowercase() }
        .let { items ->
            if (state.selectedTag.isBlank() || items.any { it.equals(state.selectedTag, ignoreCase = true) }) {
                items
            } else {
                listOf(state.selectedTag) + items
            }
        }
        .take(12)
    val showTagFilter = tags.isNotEmpty() || state.selectedTag.isNotBlank()
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        StatsSelectablePill(
            selected = true,
            onClick = onOpenMonthPicker,
            label = state.month.takeIf { it.isNotBlank() }?.let(::displayMonthLabel)
                ?: stringResource(R.string.stats_filter_all_months),
            modifier = if (showTagFilter) {
                Modifier.weight(1f)
            } else {
                Modifier.widthIn(min = 168.dp)
            },
            trailingIcon = {
                FilterTrailingIcon(
                    Icons.Filled.ExpandMore,
                    stringResource(R.string.stats_filter_pick_month_description),
                )
            },
        )
        if (showTagFilter) {
            StatsTagFilterMenu(
                tags = tags,
                selectedTag = state.selectedTag,
                onTagChange = onTagChange,
                modifier = Modifier.weight(1f),
            )
        }
    }
}

@Composable
private fun StatsTagFilterMenu(
    tags: List<String>,
    selectedTag: String,
    onTagChange: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    var expanded by remember { mutableStateOf(false) }
    Box(modifier = modifier) {
        StatsSelectablePill(
            selected = selectedTag.isNotBlank(),
            onClick = { expanded = true },
            label = selectedTag.takeIf { it.isNotBlank() }?.let { "#$it" }
                ?: stringResource(R.string.stats_filter_all_tags),
            modifier = Modifier.fillMaxWidth(),
            trailingIcon = {
                FilterTrailingIcon(
                    Icons.Filled.ExpandMore,
                    stringResource(R.string.stats_filter_tag_menu_description),
                )
            },
        )
        DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            DropdownMenuItem(
                text = { Text(stringResource(R.string.stats_filter_all_tags)) },
                onClick = {
                    expanded = false
                    onTagChange("")
                },
            )
            tags.forEach { tag ->
                DropdownMenuItem(
                    text = { Text("#$tag") },
                    onClick = {
                        expanded = false
                        onTagChange(tag)
                    },
                )
            }
        }
    }
}

@Composable
private fun StatsTextTab(
    label: String,
    selected: Boolean,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    val labelColor = when {
        !enabled -> MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.38f)
        selected -> MaterialTheme.colorScheme.primary
        else -> MaterialTheme.colorScheme.onSurfaceVariant
    }
    Column(
        modifier = Modifier
            .height(36.dp)
            .clip(RoundedCornerShape(AppRadius.extraSmall))
            .clickable(enabled = enabled, role = Role.Button, onClick = onClick)
            .padding(horizontal = AppSpacing.smallGap, vertical = AppSpacing.tinyGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap, Alignment.CenterVertically),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            text = label,
            color = labelColor,
            style = MaterialTheme.typography.labelLarge,
            fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Medium,
            maxLines = 1,
        )
        Box(
            modifier = Modifier
                .height(2.dp)
                .fillMaxWidth()
                .clip(RoundedCornerShape(AppRadius.pill))
                .background(if (selected) MaterialTheme.colorScheme.primary else Color.Transparent),
        )
    }
}

@Composable
private fun StatsSelectablePill(
    label: String,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    trailingIcon: (@Composable () -> Unit)? = null,
) {
    val visuals = LocalThemeVisuals.current
    val controlTokens = LocalStatsTokens.current.control
    val shape = RoundedCornerShape(AppRadius.pill)
    val labelColor = if (selected) {
        MaterialTheme.colorScheme.primary
    } else {
        MaterialTheme.colorScheme.onSurfaceVariant
    }
    Row(
        modifier = modifier
            .height(controlTokens.height)
            .clip(shape)
            .background(
                if (selected) {
                    visuals.chipSelected.copy(alpha = controlTokens.selectedAlpha)
                } else {
                    MaterialTheme.colorScheme.surface.copy(alpha = controlTokens.unselectedAlpha)
                },
            )
            .border(
                width = 1.dp,
                color = if (selected) {
                    MaterialTheme.colorScheme.primary.copy(alpha = controlTokens.borderAlpha)
                } else {
                    MaterialTheme.colorScheme.outlineVariant.copy(alpha = controlTokens.borderAlpha)
                },
                shape = shape,
            )
            .clickable(role = Role.Button, onClick = onClick)
            .padding(horizontal = controlTokens.horizontalPadding),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.miniGap, Alignment.CenterHorizontally),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = label,
            color = labelColor,
            style = MaterialTheme.typography.labelLarge,
            fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Medium,
            maxLines = 1,
        )
        trailingIcon?.invoke()
    }
}

@Composable
private fun FilterTrailingIcon(
    icon: ImageVector,
    contentDescription: String,
) {
    Icon(
        imageVector = icon,
        contentDescription = contentDescription,
        modifier = Modifier.size(16.dp),
    )
}
