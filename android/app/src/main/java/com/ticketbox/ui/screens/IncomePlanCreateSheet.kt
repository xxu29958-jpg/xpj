package com.ticketbox.ui.screens

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.components.AppAction
import com.ticketbox.ui.components.AppBusyGuardedSheet
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.AppSheetActionRow
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.viewmodel.IncomePlanCreateUiState
import com.ticketbox.viewmodel.IncomePlanCreateViewModel
import com.ticketbox.viewmodel.IncomePlanCreationPhase
import com.ticketbox.viewmodel.IncomePlanUiState
import com.ticketbox.viewmodel.IncomePlanViewModel
import com.ticketbox.viewmodel.updateDraftAmount
import com.ticketbox.viewmodel.updateDraftFrequency
import com.ticketbox.viewmodel.updateDraftLabel
import com.ticketbox.viewmodel.updateDraftPayDay
import com.ticketbox.viewmodel.updateDraftSource
import kotlinx.coroutines.delay

private const val CreationFlashDismissMillis = 4000L

@Composable
internal fun IncomePlanCreateAction(
    listing: IncomePlanUiState,
    state: IncomePlanCreateUiState,
    viewModel: IncomePlanCreateViewModel,
    onOpen: () -> Unit,
) {
    val retained = state.session?.takeIf { it.binding == listing.binding }
    if (!listing.canModify && retained == null) return
    AppSecondaryButton(
        text = stringResource(R.string.income_plan_add_action_short),
        enabled = retained != null || (listing.forecastMonth != null && !state.isRestoring),
        leadingIcon = Icons.Default.Add,
        onClick = {
            val month = retained?.draft?.intentMonth ?: listing.forecastMonth
            listing.binding?.let { binding ->
                if (month != null) {
                    viewModel.open(binding, month, CurrencyCode.fromStorageKeyOrNull(listing.forecastCurrencyCode))
                    onOpen()
                }
            }
        },
    )
}

@Composable
internal fun IncomeCreationSideEffects(
    state: IncomePlanCreateUiState,
    creation: IncomePlanCreateViewModel,
    listing: IncomePlanViewModel,
    closeSheet: () -> Unit,
) {
    val listingState by listing.state.collectAsStateWithLifecycle()
    LaunchedEffect(state.publishedRowId, state.binding, listingState.binding) {
        val rowId = state.publishedRowId ?: return@LaunchedEffect
        if (state.binding != listingState.binding) return@LaunchedEffect
        listing.openSubmission(rowId)
        closeSheet()
        creation.consumePublished()
    }
    LaunchedEffect(state.flashMessage) {
        if (state.flashMessage == null) return@LaunchedEffect
        delay(CreationFlashDismissMillis)
        creation.dismissFlash()
    }
}

/** 原创建由外层草稿 Owner 保留，只有 Room 接收原 key 后才关闭并接续原提交。 */
@Composable
internal fun IncomePlanAddSheetHost(
    showAddSheet: Boolean,
    state: IncomePlanCreateUiState,
    viewModel: IncomePlanCreateViewModel,
    onDismiss: () -> Unit,
) {
    if (!showAddSheet || state.session == null) return
    AppBusyGuardedSheet(isSubmitting = state.isSubmitting, onDismiss = onDismiss, skipPartiallyExpanded = true) {
        AddIncomePlanSheet(state, viewModel, onDismiss)
    }
}

@Composable
private fun AddIncomePlanSheet(
    state: IncomePlanCreateUiState,
    viewModel: IncomePlanCreateViewModel,
    onDismiss: () -> Unit,
) {
    val session = state.session ?: return
    val busy = state.isSubmitting || state.isRestoring
    val editable = session.phase == IncomePlanCreationPhase.Draft && state.canModify
    AppSheetScaffold(
        title = stringResource(R.string.income_plan_sheet_title),
        actions = {
            state.flashMessage?.let { AppStatusBanner(message = it, tone = MessageTone.Info) }
            session.admissionFailure?.let { AppStatusBanner(message = it.asUiText(), tone = MessageTone.Danger) }
            IncomePlanCreationActions(state, viewModel, onDismiss)
        },
    ) {
        if (!state.canModify) Text(stringResource(R.string.common_readonly_ledger))
        IncomePlanDraftForm(
            state = IncomePlanDraftFormState(
                draft = session.draft,
                isSubmitting = busy || !editable,
            ),
            fieldCallbacks = IncomePlanDraftFieldCallbacks(
                onLabel = viewModel::updateDraftLabel,
                onAmount = viewModel::updateDraftAmount,
                onPayDay = viewModel::updateDraftPayDay,
                onPreviousIncomeMonth = { viewModel.shiftDraftIncomeMonth(-1L) },
                onNextIncomeMonth = { viewModel.shiftDraftIncomeMonth(1L) },
            ),
            choiceCallbacks = IncomePlanDraftChoiceCallbacks(
                onSourceType = viewModel::updateDraftSource,
                onFrequency = viewModel::updateDraftFrequency,
            ),
        )
    }
}

@Composable
private fun IncomePlanCreationActions(
    state: IncomePlanCreateUiState,
    viewModel: IncomePlanCreateViewModel,
    onDismiss: () -> Unit,
) {
    val session = state.session ?: return
    val recovery = session.phase in setOf(IncomePlanCreationPhase.DraftNeedsRecovery, IncomePlanCreationPhase.NeedsRecovery)
    val busy = state.isSubmitting || state.isRestoring
    val editable = session.phase == IncomePlanCreationPhase.Draft && state.canModify
    var confirmDiscard by rememberSaveable(session.binding, session.creationKey) { mutableStateOf(false) }
    AppSheetActionRow(
        primary = AppAction(
            text = when {
                busy -> stringResource(R.string.income_plan_sheet_submitting)
                recovery -> stringResource(R.string.income_plan_creation_check_original)
                else -> stringResource(R.string.income_plan_sheet_save)
            },
            onClick = if (recovery) viewModel::retryPublicationRecovery else viewModel::submit,
            enabled = !busy && (recovery || editable),
        ),
        secondary = AppAction(
            text = stringResource(if (recovery) R.string.income_plan_creation_discard else R.string.common_cancel),
            onClick = {
                if (recovery) confirmDiscard = true else { viewModel.cancel(); onDismiss() }
            },
            enabled = !busy && session.phase != IncomePlanCreationPhase.Publishing,
        ),
    )
    if (confirmDiscard) AlertDialog(
        onDismissRequest = { confirmDiscard = false },
        title = { Text(stringResource(R.string.income_plan_creation_discard)) },
        text = { Text(stringResource(R.string.income_plan_creation_discard_explanation)) },
        confirmButton = { TextButton(enabled = !busy, onClick = {
            viewModel.cancel(discardUnresolved = true)
            confirmDiscard = false
            onDismiss()
        }) { Text(stringResource(R.string.income_plan_creation_discard_confirm)) } },
        dismissButton = { TextButton(onClick = { confirmDiscard = false }) { Text(stringResource(R.string.common_cancel)) } },
    )
}
