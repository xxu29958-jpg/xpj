package com.ticketbox.ui.screens.settings

import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.asString
import com.ticketbox.data.repository.MerchantCreationDraft
import com.ticketbox.data.repository.MerchantCreationKind
import com.ticketbox.ui.components.AppAction
import com.ticketbox.ui.components.AppActionRow
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.MerchantCreationState

@Composable
internal fun MerchantCreationReceiptEffect(state: MerchantCreationState, actions: MerchantCreationActions) {
    LaunchedEffect(state.drafts, state.binding, state.busy) {
        if (!state.busy && state.error == null) state.drafts.filter { it.phase == "accepted" && it.binding == state.binding }
            .forEach { actions.onAccepted(it.kind, it.key) }
    }
}

@Composable
internal fun MerchantCreationTask(state: MerchantAliasesScreenState, actions: MerchantAliasesScreenActions, editors: MerchantEditors) {
    val kind = if (editors.activeCreateTool == MerchantCreateTool.Catalog) MerchantCreationKind.Catalog else MerchantCreationKind.Alias
    val creation = state.creation
    val draft = creation.draft(kind)
    val pending = draft != null && draft.phase != "editing"
    SettingsOpenPanel(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        MerchantCreationInputs(creation, kind, actions.creation)
        MerchantCreationFeedback(creation, draft, kind, actions.creation)
        AppActionRow(primary = AppAction(
            text = stringResource(if (pending) R.string.merchant_creation_verify else if (kind == MerchantCreationKind.Catalog)
                R.string.merchant_catalog_create_button else R.string.merchant_aliases_create_button),
            enabled = creation.canSubmit(kind) && !state.busy,
            onClick = { if (kind == MerchantCreationKind.Catalog) actions.catalog.onCreate(draft?.displayName.orEmpty())
                else actions.alias.onCreate(draft?.canonicalMerchant.orEmpty(), draft?.alias.orEmpty()) },
        ), secondary = AppAction(text = stringResource(R.string.merchant_creation_back), enabled = true, onClick = editors::back))
    }
}

@Composable
private fun MerchantCreationInputs(state: MerchantCreationState, kind: MerchantCreationKind, actions: MerchantCreationActions) {
    val draft = state.draft(kind)
    val readOnly = !state.canEdit(kind)
    if (kind == MerchantCreationKind.Catalog) {
        SettingsDialogTextInput(SettingsTextInputState(label = stringResource(R.string.merchant_catalog_name_label), value = draft?.displayName.orEmpty(),
            placeholder = stringResource(R.string.merchant_creation_name_example), enabled = state.ready, readOnly = readOnly),
            onValueChange = { actions.onEdit(kind, it, "", "") })
    } else {
        SettingsDialogTextInput(SettingsTextInputState(label = stringResource(R.string.merchant_aliases_canonical_label), value = draft?.canonicalMerchant.orEmpty(),
            placeholder = stringResource(R.string.merchant_creation_name_example), enabled = state.ready, readOnly = readOnly),
            onValueChange = { actions.onEdit(kind, "", it, draft?.alias.orEmpty()) })
        SettingsDialogTextInput(SettingsTextInputState(label = stringResource(R.string.merchant_aliases_alias_label), value = draft?.alias.orEmpty(),
            placeholder = stringResource(R.string.merchant_creation_alias_example), enabled = state.ready, readOnly = readOnly),
            onValueChange = { actions.onEdit(kind, "", draft?.canonicalMerchant.orEmpty(), it) })
    }
}

@Composable
private fun MerchantCreationFeedback(state: MerchantCreationState, draft: MerchantCreationDraft?, kind: MerchantCreationKind, actions: MerchantCreationActions) {
    val changed = draft != null && draft.binding != state.binding
    Text(state.error?.asString() ?: stringResource(creationNotice(state, draft)), color = MaterialTheme.colorScheme.onSurfaceVariant)
    if (!state.ready && state.error != null) TextButton(enabled = !state.busy, onClick = actions.onReload) {
        Text(stringResource(R.string.merchant_creation_retry_read))
    }
    if (draft?.phase == "accepted" && state.error != null) TextButton(
        enabled = !changed && !state.busy, onClick = { actions.onAccepted(kind, draft.key) },
    ) { Text(stringResource(R.string.merchant_creation_acknowledge)) }
    draft?.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
    if (changed || draft?.phase == "rejected") TextButton(enabled = state.canModify && !state.busy, onClick = { actions.onReview(kind) }) {
        Text(stringResource(if (changed) R.string.merchant_creation_review_identity else R.string.merchant_creation_review_input))
    }
}

@StringRes
private fun creationNotice(state: MerchantCreationState, draft: MerchantCreationDraft?): Int = when {
    draft != null && draft.binding != state.binding -> R.string.merchant_creation_identity_changed
    draft?.phase == "rejected" -> R.string.merchant_creation_rejected
    draft?.phase == "accepted" -> R.string.merchant_creation_returning
    draft != null && draft.phase != "editing" -> R.string.merchant_creation_unconfirmed
    !state.ready -> R.string.merchant_creation_loading
    else -> R.string.merchant_creation_editing
}
