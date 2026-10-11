package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppFloatingActionBar
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryPageSlots
import com.ticketbox.ui.components.AppSecondaryRefreshState
import com.ticketbox.ui.components.AppSecondaryScrollableContent
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.plan.GoalEditSubmissionStatus
import com.ticketbox.viewmodel.DebtGoalEditViewModel
import com.ticketbox.viewmodel.DebtGoalEditKind

data class DebtGoalEditNavigation(val onOpen: (String) -> Unit, val onDate: (String) -> Unit,
    val retainedId: String? = null, val retainedDateId: String? = null)
data class DebtGoalScreenNavigation(val onBack: () -> Unit, val onCreate: () -> Unit,
    val onOpenLinkedDebt: (String) -> Unit, val hasCreationDraft: Boolean, val association: DebtGoalEditNavigation,
    val onOpenRecycleBin: () -> Unit)

@Composable
fun DebtGoalEditScreen(viewModel: DebtGoalEditViewModel, publicId: String, onBack: () -> Unit,
    onOpenDate: ((String) -> Unit)? = null) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    var discard by remember(publicId) { mutableStateOf(false) }
    val dateTask = state.kind == DebtGoalEditKind.TargetDate
    LaunchedEffect(viewModel, publicId) { viewModel.open(publicId) }
    AppSecondaryScrollableContent(
        chrome = AppSecondaryPageChrome(role = AppPageRole.Stats,
            title = stringResource(if (dateTask) R.string.debt_goal_date_title else R.string.debt_goal_links_title), subtitle = state.goalName,
            backText = stringResource(R.string.debt_goal_topbar_title), onBack = onBack, hasBottomBar = false),
        refresh = AppSecondaryRefreshState(isRefreshing = state.isLoading, onRefresh = viewModel::refresh),
        slots = AppSecondaryPageSlots(
            status = {
                Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                    DebtReadSource(state.fetchedAt, state.fromCache, state.isLoading)
                    state.error?.let { AppStatusBanner(it, MessageTone.Danger) }
                    if (!state.canModify) AppStatusBanner(UiText.res(R.string.debt_goal_links_read_only), MessageTone.Info)
                    state.pending?.let { GoalEditSubmissionStatus(it, state.isSaving, state.canModify, viewModel::recover) }
                }
            },
            bottomBar = {
                AppFloatingActionBar {
                    AppPrimaryButton(text = stringResource(if (dateTask) R.string.debt_goal_date_save else R.string.debt_goal_links_save), enabled = state.canSave,
                        onClick = viewModel::save, modifier = Modifier.fillMaxWidth())
                }
            },
        ),
    ) {
        debtGoalEditForm(state, viewModel, onOpenDate)
        item { AppStatusBanner(UiText.res(R.string.debt_goal_links_same_goal), MessageTone.Info) }
        if (state.hasDraft) item {
            TextButton(enabled = !state.isSaving, onClick = { discard = true }) { Text(stringResource(R.string.goal_draft_discard)) }
        }
    }
    if (discard) AlertDialog(onDismissRequest = { discard = false },
        title = { Text(stringResource(R.string.goal_draft_discard)) },
        text = { Text(stringResource(if (dateTask) R.string.debt_goal_date_discard_body else R.string.debt_goal_links_discard_body)) },
        confirmButton = { TextButton(onClick = { discard = false; viewModel.discard(); onBack() }) {
            Text(stringResource(R.string.goal_draft_discard))
        } }, dismissButton = { TextButton(onClick = { discard = false }) { Text(stringResource(R.string.common_cancel)) } })
}

private fun androidx.compose.foundation.lazy.LazyListScope.debtGoalEditForm(
    state: com.ticketbox.viewmodel.DebtGoalEditUiState, viewModel: DebtGoalEditViewModel, onOpenDate: ((String) -> Unit)?,
) {
        if (state.kind == DebtGoalEditKind.TargetDate) item {
            DebtGoalDateField(state.targetDate, state.editable && state.hasDraft, viewModel::setTargetDate)
        } else if (onOpenDate != null && state.goal?.debtRepayment?.composition == com.ticketbox.domain.model.DebtGoalComposition.External) item {
            com.ticketbox.ui.components.AppFormFieldGroup(label = stringResource(R.string.debt_goal_date_label)) {
                com.ticketbox.ui.components.AppOutlinedButton(
                    onClick = { onOpenDate(state.publicId) }, modifier = Modifier.fillMaxWidth()) {
                    Text(state.goal?.debtRepayment?.targetDate ?: stringResource(R.string.debt_goal_date_empty))
                }
            }
        }
        itemsIndexed(state.candidates, key = { _, debt -> debt.publicId }) { index, debt ->
            DebtPickerRow(debt, debt.publicId in state.selectedLabels, state.editable && state.hasDraft && !state.isLoading,
                onToggle = { viewModel.toggle(debt.publicId) }, showDivider = index < state.candidates.lastIndex)
        }
        if (state.unavailableIds.isNotEmpty()) item {
            Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                Text(stringResource(R.string.debt_goal_create_selection_changed), style = MaterialTheme.typography.bodyMedium)
                state.unavailableIds.forEach { id ->
                    Text(state.selectedLabels[id].orEmpty().ifBlank { stringResource(R.string.debt_goal_links_unavailable) })
                    TextButton(enabled = state.editable, onClick = { viewModel.toggle(id) }) {
                        Text(stringResource(R.string.debt_goal_links_remove))
                    }
                }
            }
        }
}
