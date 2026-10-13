package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.ViewModelStoreOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.R
import com.ticketbox.data.repository.ReferenceCreationActions
import com.ticketbox.data.repository.ReferenceKind
import com.ticketbox.ui.components.AppAction
import com.ticketbox.ui.components.AppBusyGuardedSheet
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSheetActionRow
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.viewmodel.ReferenceCreationUiState
import com.ticketbox.viewmodel.ReferenceCreationViewModel
import com.ticketbox.viewmodel.referenceCreationViewModelFactory

@Composable
internal fun ReferenceCreationEntry(
    repository: ReferenceCreationActions,
    owner: ViewModelStoreOwner,
    listingReady: Boolean,
    onCreated: () -> Unit,
    onRecycle: () -> Unit,
) {
    val model: ReferenceCreationViewModel = viewModel(owner, key = "reference-creation-${repository.kind.wire}",
        factory = referenceCreationViewModelFactory(repository))
    val state by model.state.collectAsStateWithLifecycle()
    val label = stringResource(if (repository.kind == ReferenceKind.Tag) R.string.reference_label_tag else R.string.reference_label_category)
    var open by rememberSaveable(repository.kind, state.binding?.ownerKey, state.binding?.ledgerId) { mutableStateOf(false) }
    var acceptedName by rememberSaveable(repository.kind, state.binding?.ownerKey, state.binding?.ledgerId) { mutableStateOf<String?>(null) }
    val draft = state.draft
    LaunchedEffect(draft?.receipt, state.bindingChanged) {
        if (draft?.receipt != null && !state.bindingChanged) {
            acceptedName = draft.receipt.name
            open = false
            onCreated()
            model.consumeReceipt(draft.key)
        }
    }
    acceptedName?.let { Text(stringResource(R.string.reference_created, it), style = MaterialTheme.typography.bodyMedium) }
    if (state.canModify || draft != null) {
        AppPrimaryButton(text = stringResource(if (draft == null) R.string.reference_add else R.string.reference_continue, label),
            enabled = listingReady && !state.busy, modifier = Modifier.fillMaxWidth(),
            onClick = { model.open(); open = true; acceptedName = null })
    }
    if (open && draft != null) {
        AppBusyGuardedSheet(isSubmitting = state.busy, onDismiss = { open = false }, skipPartiallyExpanded = true) {
            ReferenceCreationSheet(state, label, model, onDismiss = { open = false },
                onRecycle = { open = false; onRecycle() })
        }
    }
}

@Composable
private fun ReferenceCreationSheet(
    state: ReferenceCreationUiState,
    label: String,
    model: ReferenceCreationViewModel,
    onDismiss: () -> Unit,
    onRecycle: () -> Unit,
) {
    val draft = state.draft ?: return
    val editing = draft.phase == "editing"
    AppSheetScaffold(title = stringResource(R.string.reference_add, label),
        subtitle = stringResource(R.string.reference_create_subtitle),
        actions = { ReferenceCreationActions(state, label, model, onDismiss) },
    ) {
        SettingsDialogTextInput(state = SettingsTextInputState(label = stringResource(R.string.reference_name, label),
            value = draft.name, enabled = editing && state.canModify && !state.busy),
            onValueChange = model::updateName, modifier = Modifier.fillMaxWidth())
        Text(stringResource(R.string.reference_create_hint), style = MaterialTheme.typography.bodyMedium)
        if (state.bindingChanged) Text(stringResource(R.string.reference_identity_changed))
        else if (!state.canModify) Text(stringResource(R.string.reference_readonly))
        draft.error?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium) }
        if (!editing) Text(stringResource(if (draft.phase == "rejected") R.string.reference_rejected else R.string.reference_unconfirmed))
        TextButton(enabled = !state.busy, onClick = onRecycle) { Text(stringResource(R.string.reference_recycle)) }
    }
}

@Composable
private fun ReferenceCreationActions(
    state: ReferenceCreationUiState,
    label: String,
    model: ReferenceCreationViewModel,
    onDismiss: () -> Unit,
) {
    val draft = state.draft ?: return
    val rejected = draft.phase == "rejected"
    AppSheetActionRow(primary = AppAction(
        text = when {
            state.bindingChanged -> stringResource(R.string.reference_review_identity)
            rejected -> stringResource(R.string.reference_review_rejected)
            draft.phase != "editing" -> stringResource(R.string.reference_check_original)
            else -> stringResource(R.string.reference_add, label)
        },
        enabled = !state.busy && (state.canReviewIdentity || state.canModify && draft.name.isNotBlank()),
        onClick = when { state.bindingChanged -> model::reviewIdentity; rejected -> model::reviewRejected; else -> model::submit },
    ), secondary = AppAction(stringResource(R.string.reference_later), onDismiss, enabled = !state.busy))
}
