package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Checkbox
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.res.vectorResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.ticketbox.R
import com.ticketbox.domain.model.DashboardCard
import com.ticketbox.ui.components.AppAction
import com.ticketbox.ui.components.AppActionRow
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.DashboardLayoutUiState

data class DashboardLayoutActions(
    val onRefresh: () -> Unit,
    val onEdit: () -> Unit,
    val onVisible: (String, Boolean) -> Unit,
    val onMove: (String, Int) -> Unit,
    val onSave: () -> Unit,
    val onCancel: () -> Unit,
    val onReset: () -> Unit,
)

data class OverviewInteractionActions(
    val layout: DashboardLayoutActions,
    val modules: OverviewModuleActions,
)

@Composable
internal fun DashboardLayoutEditAction(state: DashboardLayoutUiState, actions: DashboardLayoutActions) {
    IconButton(onClick = actions.onEdit, enabled = state.cards != null && state.canModify && !state.saving) {
        Icon(ImageVector.vectorResource(R.drawable.ic_lucide_sliders_horizontal), contentDescription = stringResource(R.string.dashboard_customize))
    }
}

@Composable
internal fun DashboardLayoutFeedback(state: DashboardLayoutUiState, actions: DashboardLayoutActions) {
    Column {
        if (state.cards != null && !state.canModify) {
            Text(stringResource(R.string.dashboard_readonly), style = MaterialTheme.typography.bodySmall)
        }
        state.loadError?.let {
            AppStatusBanner(message = it, tone = com.ticketbox.domain.model.MessageTone.Danger)
            TextButton(onClick = actions.onRefresh, enabled = !state.loading) { Text(stringResource(R.string.common_retry)) }
        }
        if (state.draft == null) state.message?.let { AppStatusBanner(message = it, tone = state.messageTone) }
    }
}

@Composable
internal fun DashboardLayoutEditor(state: DashboardLayoutUiState, actions: DashboardLayoutActions) {
    val cards = state.draft ?: return
    Dialog(
        onDismissRequest = actions.onCancel,
        properties = DialogProperties(dismissOnBackPress = !state.saving, dismissOnClickOutside = !state.saving),
    ) {
        DashboardLayoutEditorContent(state, cards, actions)
    }
}

@Composable
internal fun DashboardLayoutEditorContent(
    state: DashboardLayoutUiState,
    cards: List<DashboardCard> = state.draft.orEmpty(),
    actions: DashboardLayoutActions,
) {
    Surface(shape = MaterialTheme.shapes.extraLarge) {
        AppSheetScaffold(
            title = stringResource(R.string.dashboard_editor_title),
            subtitle = stringResource(R.string.dashboard_editor_description),
            actions = {
                state.message?.let { AppStatusBanner(message = it, tone = state.messageTone) }
                AppActionRow(
                    primary = AppAction(stringResource(if (state.saving) R.string.common_saving else R.string.dashboard_save),
                        actions.onSave, enabled = !state.saving),
                    secondary = AppAction(stringResource(R.string.common_cancel), actions.onCancel, enabled = !state.saving),
                )
            },
        ) {
            cards.forEachIndexed { index, card ->
                key(card.key) { DashboardLayoutRow(card, index, cards.lastIndex, state.saving, actions) }
            }
            TextButton(onClick = actions.onReset, enabled = !state.saving) {
                Text(stringResource(R.string.dashboard_reset_save))
            }
        }
    }
}

@Composable
private fun DashboardLayoutRow(
    card: DashboardCard,
    index: Int,
    lastIndex: Int,
    saving: Boolean,
    actions: DashboardLayoutActions,
) {
    val visibilityLabel = stringResource(R.string.dashboard_visibility, card.title)
    val orderLabel = stringResource(R.string.dashboard_order_action, card.title, index + 1)
    var reorder by rememberSaveable { mutableStateOf(false) }
    Column(modifier = Modifier.fillMaxWidth().padding(vertical = AppSpacing.smallGap)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Checkbox(
                checked = card.visible,
                onCheckedChange = { actions.onVisible(card.key, it) },
                enabled = !saving,
                modifier = Modifier.semantics { contentDescription = visibilityLabel },
            )
            Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
                Text(card.title, style = MaterialTheme.typography.titleMedium)
                Text(
                    text = dashboardPurpose(card.key)?.let {
                        stringResource(R.string.dashboard_order_purpose, index + 1, stringResource(it))
                    } ?: stringResource(R.string.dashboard_order, index + 1),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            IconButton(onClick = { reorder = !reorder }, enabled = !saving) {
                Icon(ImageVector.vectorResource(R.drawable.ic_lucide_ellipsis), contentDescription = orderLabel)
            }
        }
        if (reorder) Row(horizontalArrangement = Arrangement.End, modifier = Modifier.fillMaxWidth()) {
            IconButton(onClick = { actions.onMove(card.key, -1) }, enabled = !saving && index > 0) {
                Icon(ImageVector.vectorResource(R.drawable.ic_lucide_chevron_up), stringResource(R.string.dashboard_move_up, card.title))
            }
            IconButton(onClick = { actions.onMove(card.key, 1) }, enabled = !saving && index < lastIndex) {
                Icon(ImageVector.vectorResource(R.drawable.ic_lucide_chevron_down), stringResource(R.string.dashboard_move_down, card.title))
            }
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
    }
}

private fun dashboardPurpose(key: String): Int? = when (key) {
    "monthly_spend" -> R.string.dashboard_purpose_monthly
    "budget" -> R.string.dashboard_purpose_budget
    "reports" -> R.string.dashboard_purpose_reports
    "goals" -> R.string.dashboard_purpose_goals
    "recurring" -> R.string.dashboard_purpose_recurring
    "pending" -> R.string.dashboard_purpose_pending
    "recent_uploads" -> R.string.dashboard_purpose_recent
    else -> null
}
