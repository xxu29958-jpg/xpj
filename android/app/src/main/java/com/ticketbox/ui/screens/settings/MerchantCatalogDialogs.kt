package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
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
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.MerchantCatalog
import com.ticketbox.domain.model.MerchantCatalogAliasPolicy
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

internal data class MerchantCatalogDialogHostActions(
    val onRename: (MerchantCatalog, String) -> Unit,
    val onMerge: (MerchantCatalog, MerchantCatalog, MerchantCatalogAliasPolicy) -> Unit,
    val onDismissSuggestion: () -> Unit,
)

internal class MerchantCatalogDialogController {
    var renamingCatalog by mutableStateOf<MerchantCatalog?>(null)
        private set
    var mergingCatalog by mutableStateOf<MerchantCatalog?>(null)
        private set
    var preselectedMergeTarget by mutableStateOf<MerchantCatalog?>(null)
        private set

    fun openRename(item: MerchantCatalog) {
        renamingCatalog = item
    }

    fun openMerge(item: MerchantCatalog) {
        preselectedMergeTarget = null
        mergingCatalog = item
    }

    fun openSuggestedMerge(source: MerchantCatalog, target: MerchantCatalog) {
        renamingCatalog = null
        preselectedMergeTarget = target
        mergingCatalog = source
    }

    fun closeRename() {
        renamingCatalog = null
    }

    fun closeMerge() {
        mergingCatalog = null
        preselectedMergeTarget = null
    }
}

@Composable
internal fun MerchantCatalogDialogHost(
    controller: MerchantCatalogDialogController,
    state: MerchantAliasesScreenState,
    actions: MerchantCatalogDialogHostActions,
) {
    LaunchedEffect(state.mergeSuggestion) {
        state.mergeSuggestion?.let { suggestion ->
            controller.openSuggestedMerge(suggestion.source, suggestion.target)
            actions.onDismissSuggestion()
        }
    }

    controller.renamingCatalog?.let { item ->
        RenameMerchantCatalogDialog(
            catalog = item,
            state = state,
            onConfirm = { newName ->
                actions.onRename(item, newName)
            },
            onDismiss = controller::closeRename,
        )
    }

    controller.mergingCatalog?.let { source ->
        val freshTarget = controller.preselectedMergeTarget
        val mergeTargets = state.catalog
            .filter { it.publicId != source.publicId && it.isActive }
            .map { if (freshTarget != null && it.publicId == freshTarget.publicId) freshTarget else it }
        MergeMerchantCatalogDialog(
            state = MerchantCatalogMergeDialogState(
                source = source,
                targets = mergeTargets,
                initialTarget = freshTarget?.takeIf { it.isActive },
                busy = state.busy,
                message = state.message,
                messageTone = state.messageTone,
            ),
            actions = MerchantCatalogMergeDialogActions(
                onConfirm = { target, aliasPolicy ->
                    actions.onMerge(source, target, aliasPolicy)
                },
                onDismiss = controller::closeMerge,
            ),
        )
    }
}

@Composable
private fun RenameMerchantCatalogDialog(
    catalog: MerchantCatalog,
    state: MerchantAliasesScreenState,
    onConfirm: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    var name by remember(catalog.publicId) { mutableStateOf(catalog.displayName) }
    AlertDialog(
        onDismissRequest = { if (!state.busy) onDismiss() },
        title = { Text(stringResource(R.string.merchant_catalog_rename_dialog_title)) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                SettingsDialogTextInput(
                    state = SettingsTextInputState(
                        label = stringResource(R.string.merchant_catalog_rename_dialog_label),
                        value = name,
                        enabled = !state.busy,
                    ),
                    onValueChange = { name = it },
                    modifier = Modifier.fillMaxWidth(),
                )
                AppStatusBanner(message = state.message, tone = state.messageTone)
            }
        },
        confirmButton = {
            TextButton(
                enabled = !state.busy && name.trim().isNotBlank() && name.trim() != catalog.displayName,
                onClick = { onConfirm(name) },
            ) {
                Text(stringResource(R.string.merchant_catalog_rename_dialog_confirm))
            }
        },
        dismissButton = {
            TextButton(enabled = !state.busy, onClick = onDismiss) { Text(stringResource(R.string.common_cancel)) }
        },
    )
}

private data class MerchantCatalogMergeDialogState(
    val source: MerchantCatalog,
    val targets: List<MerchantCatalog>,
    val initialTarget: MerchantCatalog?,
    val busy: Boolean,
    val message: UiText?,
    val messageTone: MessageTone,
)

private data class MerchantCatalogMergeDialogActions(
    val onConfirm: (MerchantCatalog, MerchantCatalogAliasPolicy) -> Unit,
    val onDismiss: () -> Unit,
)

@Composable
private fun MergeMerchantCatalogDialog(
    state: MerchantCatalogMergeDialogState,
    actions: MerchantCatalogMergeDialogActions,
) {
    var selectedTarget by remember(state.source.publicId) { mutableStateOf(state.initialTarget) }
    var aliasPolicy by remember(state.source.publicId) { mutableStateOf<MerchantCatalogAliasPolicy?>(null) }
    AlertDialog(
        onDismissRequest = { if (!state.busy) actions.onDismiss() },
        title = { Text(stringResource(R.string.merchant_catalog_merge_dialog_title)) },
        text = {
            MergeMerchantCatalogDialogContent(
                state = MerchantCatalogMergeContentState(
                    source = state.source,
                    targets = state.targets,
                    selectedTarget = selectedTarget,
                    aliasPolicy = aliasPolicy,
                    busy = state.busy,
                    message = state.message,
                    messageTone = state.messageTone,
                ),
                actions = MerchantCatalogMergeContentActions(
                    onSelectTarget = { selectedTarget = it },
                    onSelectAliasPolicy = { aliasPolicy = it },
                ),
            )
        },
        confirmButton = {
            TextButton(
                enabled = !state.busy && selectedTarget != null && aliasPolicy != null,
                onClick = {
                    val target = selectedTarget ?: return@TextButton
                    val policy = aliasPolicy ?: return@TextButton
                    actions.onConfirm(target, policy)
                },
            ) {
                Text(stringResource(R.string.merchant_catalog_merge_dialog_confirm))
            }
        },
        dismissButton = {
            TextButton(enabled = !state.busy, onClick = actions.onDismiss) { Text(stringResource(R.string.common_cancel)) }
        },
    )
}

private data class MerchantCatalogMergeContentState(
    val source: MerchantCatalog,
    val targets: List<MerchantCatalog>,
    val selectedTarget: MerchantCatalog?,
    val aliasPolicy: MerchantCatalogAliasPolicy?,
    val busy: Boolean,
    val message: UiText?,
    val messageTone: MessageTone,
)

private data class MerchantCatalogMergeContentActions(
    val onSelectTarget: (MerchantCatalog) -> Unit,
    val onSelectAliasPolicy: (MerchantCatalogAliasPolicy) -> Unit,
)

@Composable
private fun MergeMerchantCatalogDialogContent(
    state: MerchantCatalogMergeContentState,
    actions: MerchantCatalogMergeContentActions,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(max = 360.dp)
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        Text(
            text = stringResource(R.string.merchant_catalog_merge_dialog_text, state.source.displayName),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodyMedium,
        )
        MerchantCatalogMergeTargetList(state.targets, state.selectedTarget, !state.busy, actions.onSelectTarget)
        MerchantCatalogAliasPolicySection(state.aliasPolicy, !state.busy, actions.onSelectAliasPolicy)
        AppStatusBanner(message = state.message, tone = state.messageTone)
    }
}

@Composable
private fun MerchantCatalogMergeTargetList(
    targets: List<MerchantCatalog>,
    selectedTarget: MerchantCatalog?,
    enabled: Boolean,
    onSelectTarget: (MerchantCatalog) -> Unit,
) {
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
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
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
        Text(text = label, maxLines = 2, overflow = TextOverflow.Ellipsis)
    }
}
