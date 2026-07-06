package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DashboardCustomize
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material.icons.filled.RestartAlt
import androidx.compose.material.icons.filled.Save
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.domain.model.DashboardCard
import com.ticketbox.ui.components.AppAdaptiveEditActionLayout
import com.ticketbox.ui.components.AppAdaptiveEditActionMode
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.AppSwitch
import com.ticketbox.ui.components.DraggableReorderColumn
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.DashboardCardsUiState

data class DashboardCardsScreenActions(
    val onMoveCard: (Int, Int) -> Unit,
    val onReorder: (Int, Int) -> Unit,
    val onVisibleChange: (String, Boolean) -> Unit,
    val onSave: () -> Unit,
    val onReset: () -> Unit,
)

@Composable
fun DashboardCardsScreen(
    state: DashboardCardsUiState,
    onBack: () -> Unit,
    actions: DashboardCardsScreenActions,
) {
    SettingsPageFrame(
        title = stringResource(R.string.dashboard_cards_page_title),
        subtitle = if (state.canModify) {
            stringResource(R.string.dashboard_cards_page_subtitle_default)
        } else {
            stringResource(R.string.dashboard_cards_page_subtitle_readonly)
        },
        onBack = onBack,
        status = { AppStatusBanner(message = state.message, tone = state.messageTone) },
    ) {
        DashboardCardsOverviewSection(cards = state.cards)
        DashboardCardsOrderSection(state = state, actions = actions)
    }
}

@Composable
private fun DashboardCardsOverviewSection(cards: List<DashboardCard>) {
    val summary = dashboardCardsSummary(cards)
    SettingsSection(
        title = stringResource(R.string.dashboard_cards_section_overview),
        icon = Icons.Filled.DashboardCustomize,
    ) {
        SettingsOpenPanel(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
            SettingsMetricGrid(
                metrics = listOf(
                    SettingsMetricData(
                        label = stringResource(R.string.dashboard_cards_overview_visible_label),
                        value = summary.visibleCount.toString(),
                        caption = stringResource(R.string.dashboard_cards_overview_visible_caption, summary.totalCount),
                    ),
                    SettingsMetricData(
                        label = stringResource(R.string.dashboard_cards_overview_hidden_label),
                        value = summary.hiddenCount.toString(),
                        caption = stringResource(R.string.dashboard_cards_overview_hidden_caption),
                    ),
                ),
            )
            Text(
                text = summary.firstVisibleTitle?.let {
                    stringResource(R.string.dashboard_cards_overview_first_visible, it)
                } ?: stringResource(R.string.dashboard_cards_overview_none_visible),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun DashboardCardsOrderSection(
    state: DashboardCardsUiState,
    actions: DashboardCardsScreenActions,
) {
    SettingsSection(
        title = stringResource(R.string.dashboard_cards_section_order),
        icon = Icons.Filled.DashboardCustomize,
    ) {
        when {
            state.cards.isEmpty() -> SettingsListStateSlot(
                loading = state.loading,
                hasData = false,
                copy = SettingsStateSlotCopy(
                    loadingTitle = stringResource(R.string.dashboard_cards_loading_title),
                    loadingBody = stringResource(R.string.dashboard_cards_loading_body),
                    emptyText = stringResource(R.string.dashboard_cards_empty_body),
                    emptyTitle = stringResource(R.string.dashboard_cards_empty_title),
                    emptyBody = stringResource(R.string.dashboard_cards_empty_body),
                ),
            )
            else -> DashboardCardsList(state = state, actions = actions)
        }
    }
}

@Composable
private fun DashboardCardsList(
    state: DashboardCardsUiState,
    actions: DashboardCardsScreenActions,
) {
    val enabled = state.canModify && !state.saving
    SettingsOpenPanel(verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap)) {
        DraggableReorderColumn(
            items = state.cards,
            key = { it.key },
            spacing = AppSpacing.compactGap,
            estimatedItemHeight = AppSpacing.controlMinHeight + AppSpacing.cardPaddingSmall,
            enabled = enabled,
            onMove = actions.onReorder,
        ) { index, card, _ ->
            DashboardCardRow(
                row = DashboardCardRowState(
                    card = card,
                    index = index,
                    canMoveUp = index > 0,
                    canMoveDown = index < state.cards.lastIndex,
                    enabled = enabled,
                ),
                actions = actions,
            )
        }
        DashboardCardsFooter(state = state, actions = actions)
    }
}

@Composable
private fun DashboardCardsFooter(
    state: DashboardCardsUiState,
    actions: DashboardCardsScreenActions,
) {
    when {
        !state.canModify -> Text(
            text = stringResource(R.string.dashboard_cards_readonly_hint),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
        state.dirty -> Text(
            text = stringResource(R.string.dashboard_cards_unsaved_hint),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
    }
    DashboardCardsFooterActions(state = state, actions = actions)
}

@Composable
private fun DashboardCardsFooterActions(
    state: DashboardCardsUiState,
    actions: DashboardCardsScreenActions,
) {
    val resetEnabled = state.canModify && !state.saving
    val saveEnabled = state.canModify && !state.saving && state.cards.isNotEmpty() && state.dirty
    val saveText = if (state.saving) {
        stringResource(R.string.dashboard_cards_save_busy)
    } else {
        stringResource(R.string.dashboard_cards_save_button)
    }
    val resetAction: @Composable (Modifier) -> Unit = { actionModifier ->
        QuietOutlinedButton(
            text = stringResource(R.string.dashboard_cards_reset_button),
            modifier = actionModifier,
            enabled = resetEnabled,
            leadingIcon = Icons.Filled.RestartAlt,
            onClick = actions.onReset,
        )
    }
    val saveAction: @Composable (Modifier) -> Unit = { actionModifier ->
        AppPrimaryButton(
            text = saveText,
            icon = Icons.Filled.Save,
            modifier = actionModifier,
            enabled = saveEnabled,
            onClick = actions.onSave,
        )
    }
    AppAdaptiveEditActionLayout(actionCount = 2, compact = false, stackTwoActionsOnNarrow = true) { mode ->
        when (mode) {
            AppAdaptiveEditActionMode.Stacked -> Column(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
            ) {
                resetAction(Modifier.fillMaxWidth())
                saveAction(Modifier.fillMaxWidth())
            }
            AppAdaptiveEditActionMode.Compact,
            AppAdaptiveEditActionMode.Inline -> Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap, Alignment.End),
            ) {
                resetAction(Modifier)
                saveAction(Modifier)
            }
        }
    }
}

private data class DashboardCardRowState(
    val card: DashboardCard,
    val index: Int,
    val canMoveUp: Boolean,
    val canMoveDown: Boolean,
    val enabled: Boolean,
)

@Composable
private fun DashboardCardRow(
    row: DashboardCardRowState,
    actions: DashboardCardsScreenActions,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = AppSpacing.miniGap),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
            ) {
                Text(
                    text = row.card.title,
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    text = if (row.card.visible) {
                        stringResource(R.string.dashboard_cards_card_visible)
                    } else {
                        stringResource(R.string.dashboard_cards_card_hidden)
                    },
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelSmall,
                )
            }
            DashboardCardMoveButton(
                enabled = row.enabled && row.canMoveUp,
                icon = Icons.Filled.KeyboardArrowUp,
                contentDescription = stringResource(R.string.dashboard_cards_move_up_content_description, row.card.title),
                onClick = { actions.onMoveCard(row.index, -1) },
            )
            DashboardCardMoveButton(
                enabled = row.enabled && row.canMoveDown,
                icon = Icons.Filled.KeyboardArrowDown,
                contentDescription = stringResource(R.string.dashboard_cards_move_down_content_description, row.card.title),
                onClick = { actions.onMoveCard(row.index, 1) },
            )
            AppSwitch(
                checked = row.card.visible,
                enabled = row.enabled,
                contentDescription = stringResource(
                    R.string.dashboard_cards_toggle_content_description,
                    row.card.title,
                ),
                onCheckedChange = { actions.onVisibleChange(row.card.key, it) },
            )
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium))
    }
}

@Composable
private fun DashboardCardMoveButton(
    enabled: Boolean,
    icon: ImageVector,
    contentDescription: String,
    onClick: () -> Unit,
) {
    IconButton(
        enabled = enabled,
        onClick = onClick,
    ) {
        Icon(icon, contentDescription = contentDescription)
    }
}
