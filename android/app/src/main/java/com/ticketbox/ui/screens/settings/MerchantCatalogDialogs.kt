package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.data.repository.MerchantDraft
import com.ticketbox.data.repository.MerchantDraftKind
import com.ticketbox.ui.asString
import com.ticketbox.domain.model.MerchantCatalog
import com.ticketbox.domain.model.MerchantCatalogAliasPolicy
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

internal class MerchantCatalogDialogController {
    var kind by mutableStateOf<MerchantDraftKind?>(null)
        private set
    var sourceId by mutableStateOf<String?>(null)
        private set
    private var returnToRename: String? = null

    fun open(next: MerchantDraftKind, id: String) {
        returnToRename = null
        kind = next
        sourceId = id
    }

    fun openSuggestedMerge(id: String) {
        returnToRename = sourceId.takeIf { kind == MerchantDraftKind.Rename && it == id }
        kind = MerchantDraftKind.Merge
        sourceId = id
    }

    fun close() {
        sourceId = returnToRename
        kind = returnToRename?.let { MerchantDraftKind.Rename }
        returnToRename = null
    }

    fun complete(completed: MerchantDraftKind, id: String) {
        if (kind != completed || sourceId != id) return
        returnToRename = null
        close()
    }
}

@Composable
internal fun MerchantCatalogDialogHost(
    controller: MerchantCatalogDialogController,
    state: MerchantAliasesScreenState,
    actions: MerchantAliasesScreenActions,
) {
    LaunchedEffect(state.mergeSuggestion) {
        state.mergeSuggestion?.let {
            actions.catalog.onSuggestMerge(it.source, it.target)
            controller.openSuggestedMerge(it.source.publicId)
            actions.mergeSuggestion.onDismiss()
        }
    }
    val kind = controller.kind ?: return
    val draft = state.drafts.draft(kind, controller.sourceId) ?: return
    AlertDialog(
        onDismissRequest = { if (!state.busy) controller.close() },
        title = { Text(stringResource(merchantCommandTitle(kind))) },
        text = {
            Column(modifier = Modifier.verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                MerchantCatalogCommandInputs(draft, state, actions.catalog)
                MerchantCatalogCommandFeedback(draft, state, actions)
            }
        },
        confirmButton = {
            TextButton(enabled = !state.busy && state.drafts.canSubmit(draft),
                onClick = { actions.catalog.onSubmit(kind, controller.sourceId) }) {
                Text(stringResource(if (draft.phase == "unconfirmed") R.string.merchant_command_verify else merchantCommandConfirm(draft)))
            }
        },
        dismissButton = {
            TextButton(enabled = !state.busy, onClick = controller::close) { Text(stringResource(R.string.common_cancel)) }
        },
    )
}

@Composable
private fun MerchantCatalogCommandInputs(draft: MerchantDraft, state: MerchantAliasesScreenState, actions: MerchantAliasesCatalogActions) {
    val source = requireNotNull(draft.source)
    val editable = state.drafts.canEdit(draft) && !state.busy
    when (draft.kind) {
        MerchantDraftKind.Rename -> {
            Text(stringResource(if (draft.sourceUnavailable || !draft.reviewed) R.string.merchant_rename_original_name else R.string.merchant_rename_current_name,
                source.displayName))
            SettingsDialogTextInput(SettingsTextInputState(label = stringResource(R.string.merchant_catalog_rename_dialog_label),
                value = draft.displayName, enabled = state.drafts.ready, readOnly = !editable),
                onValueChange = { actions.onChange(draft.copy(displayName = it)) }, modifier = Modifier.fillMaxWidth())
        }
        MerchantDraftKind.Merge -> {
            Text(stringResource(R.string.merchant_catalog_merge_dialog_text, source.displayName))
            draft.target?.let { Text(stringResource(R.string.merchant_merge_selected_target, it.displayName)) }
            MerchantCatalogMergeTargetList(state.catalog, draft, editable) { actions.onChange(draft.copy(target = it)) }
            MerchantCatalogAliasPolicySection(draft.aliasPolicy, editable) { actions.onChange(draft.copy(aliasPolicy = it)) }
        }
        MerchantDraftKind.Delete -> Text(stringResource(R.string.merchant_catalog_delete_dialog_text, source.displayName))
        MerchantDraftKind.Visibility -> Text(stringResource(if (draft.nextStatus == "hidden") R.string.merchant_command_hide_text
            else R.string.merchant_command_show_text, source.displayName))
        else -> Unit
    }
}

@Composable
private fun MerchantCatalogCommandFeedback(draft: MerchantDraft, state: MerchantAliasesScreenState, actions: MerchantAliasesScreenActions) {
    val changed = draft.binding != state.drafts.binding
    Text(state.drafts.error?.asString() ?: merchantCommandNotice(draft, changed), color = MaterialTheme.colorScheme.onSurfaceVariant)
    draft.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
    if (draft.phase == "accepted" && state.drafts.error != null) TextButton(
        enabled = !changed && !state.busy, onClick = { actions.creation.onAccepted(draft.kind, draft.key) },
    ) { Text(stringResource(R.string.merchant_creation_acknowledge)) }
    if (draft.phase != "accepted" || changed) TextButton(enabled = state.drafts.canReview(draft) && !state.busy,
        onClick = { actions.catalog.onReview(draft.kind, draft.source?.publicId) }) {
        Text(stringResource(if (changed) R.string.merchant_creation_review_identity else if (draft.kind == MerchantDraftKind.Merge)
            R.string.merchant_merge_review else if (draft.kind == MerchantDraftKind.Rename) R.string.merchant_rename_review
            else R.string.merchant_command_review))
    }
}

@Composable
private fun merchantCommandNotice(draft: MerchantDraft, changed: Boolean): String = when {
        changed -> stringResource(R.string.merchant_creation_identity_changed)
        draft.sourceUnavailable -> stringResource(when (draft.kind) {
            MerchantDraftKind.Merge -> R.string.merchant_merge_source_unavailable
            MerchantDraftKind.Rename -> R.string.merchant_rename_unavailable
            else -> R.string.merchant_command_source_unavailable
        })
        draft.targetUnavailable -> stringResource(R.string.merchant_merge_target_unavailable)
        draft.phase == "unconfirmed" -> stringResource(R.string.merchant_command_unconfirmed)
        draft.phase == "rejected" -> stringResource(R.string.merchant_command_rejected)
        draft.phase == "accepted" -> stringResource(R.string.merchant_command_returning)
        draft.reviewed -> merchantReviewedNotice(draft)
        else -> stringResource(R.string.merchant_command_editing)
    }

@Composable
private fun merchantReviewedNotice(draft: MerchantDraft): String = if (draft.kind == MerchantDraftKind.Merge && draft.target != null)
    stringResource(R.string.merchant_merge_reviewed, requireNotNull(draft.source).displayName, draft.target.displayName)
    else stringResource(R.string.merchant_rename_reviewed)

internal fun merchantCommandTitle(kind: MerchantDraftKind): Int = when (kind) {
    MerchantDraftKind.Rename -> R.string.merchant_catalog_rename_dialog_title
    MerchantDraftKind.Merge -> R.string.merchant_catalog_merge_dialog_title
    MerchantDraftKind.Delete -> R.string.merchant_catalog_delete_dialog_title
    else -> R.string.merchant_command_visibility
}

private fun merchantCommandConfirm(draft: MerchantDraft): Int = when (draft.kind) {
    MerchantDraftKind.Rename -> R.string.merchant_catalog_rename_dialog_confirm
    MerchantDraftKind.Merge -> R.string.merchant_catalog_merge_dialog_confirm
    MerchantDraftKind.Delete -> R.string.merchant_catalog_delete_dialog_confirm
    else -> if (draft.nextStatus == "hidden") R.string.merchant_catalog_card_action_hide else R.string.merchant_catalog_card_action_show
}

@Composable
private fun MerchantCatalogMergeTargetList(
    catalog: List<MerchantCatalog>,
    draft: MerchantDraft,
    enabled: Boolean,
    onSelectTarget: (MerchantCatalog) -> Unit,
) {
    // Frozen commands show their original selected target above, independently of today's directory choices.
    if (draft.phase != "editing") return
    val selectedTarget = draft.target
    val targets = catalog.filter { it.publicId != draft.source?.publicId && it.isActive && it.deletedAt == null }
        .map { if (it.publicId == selectedTarget?.publicId) requireNotNull(selectedTarget) else it }
    if (targets.isEmpty()) {
        Text(
            text = stringResource(R.string.merchant_catalog_merge_dialog_no_targets),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    } else {
        targets.forEach { target ->
            MerchantCatalogMergeTargetRow(
                target = target,
                selected = selectedTarget?.publicId == target.publicId,
                enabled = enabled,
                onSelect = { onSelectTarget(target) },
            )
        }
    }
}

@Composable
private fun MerchantCatalogAliasPolicySection(
    aliasPolicy: MerchantCatalogAliasPolicy?,
    enabled: Boolean,
    onSelectAliasPolicy: (MerchantCatalogAliasPolicy) -> Unit,
) {
    Text(
        text = stringResource(R.string.merchant_catalog_merge_alias_policy_title),
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        style = MaterialTheme.typography.bodyMedium,
        fontWeight = AppTextHierarchy.body.weight,
    )
    MerchantCatalogAliasPolicyRow(
        label = stringResource(R.string.merchant_catalog_merge_alias_policy_none),
        selected = aliasPolicy == MerchantCatalogAliasPolicy.None,
        enabled = enabled,
        onSelect = { onSelectAliasPolicy(MerchantCatalogAliasPolicy.None) },
    )
    MerchantCatalogAliasPolicyRow(
        label = stringResource(R.string.merchant_catalog_merge_alias_policy_create_source_alias),
        selected = aliasPolicy == MerchantCatalogAliasPolicy.CreateSourceAlias,
        enabled = enabled,
        onSelect = { onSelectAliasPolicy(MerchantCatalogAliasPolicy.CreateSourceAlias) },
    )
    Text(
        text = stringResource(R.string.merchant_catalog_merge_alias_policy_hint),
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        style = MaterialTheme.typography.bodySmall,
    )
}

@Composable
private fun MerchantCatalogMergeTargetRow(
    target: MerchantCatalog,
    selected: Boolean,
    enabled: Boolean,
    onSelect: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .selectable(selected = selected, enabled = enabled, onClick = onSelect)
            .padding(vertical = AppSpacing.smallGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        RadioButton(selected = selected, enabled = enabled, onClick = onSelect)
        Spacer(Modifier.width(AppSpacing.smallGap))
        Text(
            text = if (target.usageCount > 0) {
                stringResource(R.string.merchant_catalog_merge_dialog_target_with_count, target.displayName, target.usageCount)
            } else {
                target.displayName
            },
            modifier = Modifier.weight(1f),
        )
    }
}

@Composable
private fun MerchantCatalogAliasPolicyRow(
    label: String,
    selected: Boolean,
    enabled: Boolean,
    onSelect: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .selectable(selected = selected, enabled = enabled, onClick = onSelect)
            .padding(vertical = AppSpacing.tinyGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        RadioButton(selected = selected, enabled = enabled, onClick = onSelect)
        Spacer(Modifier.width(AppSpacing.smallGap))
        Text(text = label, modifier = Modifier.weight(1f))
    }
}
