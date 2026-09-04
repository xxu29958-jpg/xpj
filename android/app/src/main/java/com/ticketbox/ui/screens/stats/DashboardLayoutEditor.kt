package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.ticketbox.R
import com.ticketbox.domain.model.DashboardCard
import com.ticketbox.ui.components.AppPrimaryButton
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
internal fun DashboardLayoutEntry(state: DashboardLayoutUiState, actions: DashboardLayoutActions) {
    Column {
        TextButton(onClick = actions.onEdit, enabled = state.cards != null && state.canModify && !state.saving) {
            Text(stringResource(R.string.dashboard_customize))
        }
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
        Column(
            modifier = Modifier.padding(AppSpacing.cardPaddingSmall),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
                Text(stringResource(R.string.dashboard_editor_title), style = MaterialTheme.typography.titleLarge)
                LazyColumn(modifier = Modifier.weight(1f, fill = false)) {
                    item { Text(stringResource(R.string.dashboard_editor_description), style = MaterialTheme.typography.bodySmall) }
                    itemsIndexed(cards, key = { _, card -> card.key }) { index, card ->
                        DashboardLayoutRow(card, index, cards.lastIndex, state.saving, actions)
                    }
                    item {
                        TextButton(onClick = actions.onReset, enabled = !state.saving) {
                            Text(stringResource(R.string.dashboard_reset_save))
                        }
                    }
                }
                state.message?.let { AppStatusBanner(message = it, tone = state.messageTone) }
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap, Alignment.End),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    TextButton(onClick = actions.onCancel, enabled = !state.saving) { Text(stringResource(R.string.common_cancel)) }
                    AppPrimaryButton(
                        icon = Icons.Default.Check,
                        text = stringResource(if (state.saving) R.string.common_saving else R.string.dashboard_save),
                        enabled = !state.saving,
                        onClick = actions.onSave,
                    )
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
    Column(modifier = Modifier.fillMaxWidth().padding(vertical = AppSpacing.smallGap)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(card.title, modifier = Modifier.weight(1f), style = MaterialTheme.typography.titleSmall)
            Switch(
                checked = card.visible,
                onCheckedChange = { actions.onVisible(card.key, it) },
                enabled = !saving,
                modifier = Modifier.semantics { contentDescription = visibilityLabel },
            )
        }
        Row(horizontalArrangement = Arrangement.End, modifier = Modifier.fillMaxWidth()) {
            IconButton(onClick = { actions.onMove(card.key, -1) }, enabled = !saving && index > 0) {
                Icon(Icons.Default.KeyboardArrowUp, stringResource(R.string.dashboard_move_up, card.title))
            }
            IconButton(onClick = { actions.onMove(card.key, 1) }, enabled = !saving && index < lastIndex) {
                Icon(Icons.Default.KeyboardArrowDown, stringResource(R.string.dashboard_move_down, card.title))
            }
        }
    }
}
