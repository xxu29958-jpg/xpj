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
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.MerchantCatalog
import com.ticketbox.domain.model.MerchantCatalogAliasPolicy
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.viewmodel.MerchantRenameReview
import com.ticketbox.viewmodel.MerchantMergeReview

internal data class MerchantCatalogDialogHostActions(
    val onRename: (MerchantCatalog, String) -> Unit,
    val onMerge: (MerchantCatalog, MerchantCatalog, MerchantCatalogAliasPolicy) -> Unit,
    val onDismissSuggestion: () -> Unit,
    val onReviewRename: (MerchantCatalog) -> Unit,
    val onConsumeRenameReview: () -> Unit,
    val onReviewMerge: (MerchantCatalog, MerchantCatalog) -> Unit,
    val onConsumeMergeReview: () -> Unit,
)

internal class MerchantCatalogDialogController {
    var renamingCatalog by mutableStateOf<MerchantCatalog?>(null)
        private set
    var renameUnavailable by mutableStateOf(false)
        private set
    var renameName by mutableStateOf("")
    var mergingCatalog by mutableStateOf<MerchantCatalog?>(null)
        private set
    var selectedMergeTarget by mutableStateOf<MerchantCatalog?>(null)
        private set
    var mergeAliasPolicy by mutableStateOf<MerchantCatalogAliasPolicy?>(null)
    var mergeSourceUnavailable by mutableStateOf(false)
        private set
    var mergeTargetUnavailable by mutableStateOf(false)
        private set

    fun openRename(item: MerchantCatalog) {
        renamingCatalog = item
        renameUnavailable = false
        renameName = item.displayName
    }

    fun reviewRename(review: MerchantRenameReview) {
        if (renamingCatalog != review.original) return
        renameUnavailable = review.current == null
        review.current?.let { renamingCatalog = it }
    }

    fun openMerge(item: MerchantCatalog) {
        closeMerge()
        mergingCatalog = item
    }

    fun openSuggestedMerge(source: MerchantCatalog, target: MerchantCatalog) {
        openMerge(source)
        selectedMergeTarget = target
    }

    fun selectMergeTarget(target: MerchantCatalog) {
        if (selectedMergeTarget?.publicId == target.publicId) return
        selectedMergeTarget = target
        mergeTargetUnavailable = false
    }

    fun reviewMerge(review: MerchantMergeReview) {
        if (mergingCatalog != review.originalSource || selectedMergeTarget != review.originalTarget) return
        reviewRename(MerchantRenameReview(review.originalSource, review.source))
        mergeSourceUnavailable = review.source == null
        mergeTargetUnavailable = review.target == null
        review.source?.let { mergingCatalog = it }
        review.target?.let { selectedMergeTarget = it }
    }

    fun closeRename() {
        renamingCatalog = null
        renameName = ""
    }

    fun closeMerge() {
        mergingCatalog = null
        selectedMergeTarget = null
        mergeAliasPolicy = null
        mergeSourceUnavailable = false
        mergeTargetUnavailable = false
    }

    fun finishMerge() {
        if (renamingCatalog?.publicId == mergingCatalog?.publicId) closeRename()
        closeMerge()
    }
}

@Composable
internal fun MerchantCatalogDialogHost(
    controller: MerchantCatalogDialogController,
    state: MerchantAliasesScreenState,
    actions: MerchantCatalogDialogHostActions,
) {
    LaunchedEffect(state.renameReview, state.mergeSuggestion, state.mergeReview) {
        state.renameReview?.let {
            controller.reviewRename(it)
            actions.onConsumeRenameReview()
        }
        state.mergeSuggestion?.let { suggestion ->
            controller.openSuggestedMerge(suggestion.source, suggestion.target)
            actions.onDismissSuggestion()
        }
        state.mergeReview?.let {
            controller.reviewMerge(it)
            actions.onConsumeMergeReview()
        }
    }

    controller.renamingCatalog?.takeIf { controller.mergingCatalog == null }?.let { item ->
        RenameMerchantCatalogDialog(
            catalog = item,
            state = state,
            unavailable = controller.renameUnavailable,
            name = controller.renameName,
            actions = MerchantRenameActions(
                onNameChange = { controller.renameName = it },
                onConfirm = { newName -> actions.onRename(item, newName) },
                onReview = { actions.onReviewRename(item) },
                onDismiss = controller::closeRename,
            ),
        )
    }

    controller.mergingCatalog?.let { source ->
        val selectedTarget = controller.selectedMergeTarget
        val mergeTargets = state.catalog
            .filter { it.publicId != source.publicId && it.isActive && it.deletedAt == null }
            .map { if (selectedTarget != null && it.publicId == selectedTarget.publicId) selectedTarget else it }
        MergeMerchantCatalogDialog(
            state = MerchantCatalogMergeDialogState(
                source = source,
                targets = mergeTargets,
                selectedTarget = selectedTarget,
                aliasPolicy = controller.mergeAliasPolicy,
                busy = state.busy,
                readOnly = state.readOnly,
                unavailable = controller.mergeSourceUnavailable || controller.mergeTargetUnavailable,
                message = state.message,
                messageTone = state.messageTone,
            ),
            actions = MerchantCatalogMergeDialogActions(
                onConfirm = { target, aliasPolicy ->
                    actions.onMerge(source, target, aliasPolicy)
                },
                onDismiss = controller::closeMerge,
                onReview = { selectedTarget?.let { actions.onReviewMerge(source, it) } },
                onSelectTarget = controller::selectMergeTarget,
                onSelectAliasPolicy = { controller.mergeAliasPolicy = it },
            ),
        )
    }
}

@Composable
private fun RenameMerchantCatalogDialog(
    catalog: MerchantCatalog,
    state: MerchantAliasesScreenState,
    unavailable: Boolean,
    name: String,
    actions: MerchantRenameActions,
) {
    AlertDialog(
        onDismissRequest = { if (!state.busy) actions.onDismiss() },
        title = { Text(stringResource(R.string.merchant_catalog_rename_dialog_title)) },
        text = {
            Column(modifier = Modifier.verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                Text(stringResource(if (unavailable) R.string.merchant_rename_original_name
                    else R.string.merchant_rename_current_name, catalog.displayName))
                SettingsDialogTextInput(
                    state = SettingsTextInputState(
                        label = stringResource(R.string.merchant_catalog_rename_dialog_label),
                        value = name,
                        enabled = !state.busy && !state.readOnly,
                    ),
                    onValueChange = actions.onNameChange,
                    modifier = Modifier.fillMaxWidth(),
                )
                AppStatusBanner(message = state.message, tone = state.messageTone)
                TextButton(enabled = !state.busy, onClick = actions.onReview) {
                    Text(stringResource(R.string.merchant_rename_review))
                }
            }
        },
        confirmButton = {
            TextButton(
                enabled = !state.busy && !state.readOnly && !unavailable &&
                    name.trim().isNotBlank() && name.trim() != catalog.displayName,
                onClick = { actions.onConfirm(name) },
            ) {
                Text(stringResource(R.string.merchant_catalog_rename_dialog_confirm))
            }
        },
        dismissButton = {
            TextButton(enabled = !state.busy, onClick = actions.onDismiss) { Text(stringResource(R.string.common_cancel)) }
        },
    )
}

private data class MerchantRenameActions(
    val onNameChange: (String) -> Unit,
    val onConfirm: (String) -> Unit,
    val onReview: () -> Unit,
    val onDismiss: () -> Unit,
)

private data class MerchantCatalogMergeDialogState(
    val source: MerchantCatalog,
    val targets: List<MerchantCatalog>,
    val selectedTarget: MerchantCatalog?,
    val aliasPolicy: MerchantCatalogAliasPolicy?,
    val busy: Boolean,
    val readOnly: Boolean,
    val unavailable: Boolean,
    val message: UiText?,
    val messageTone: MessageTone,
)

private data class MerchantCatalogMergeDialogActions(
    val onConfirm: (MerchantCatalog, MerchantCatalogAliasPolicy) -> Unit,
    val onDismiss: () -> Unit,
    val onReview: () -> Unit,
    val onSelectTarget: (MerchantCatalog) -> Unit,
    val onSelectAliasPolicy: (MerchantCatalogAliasPolicy) -> Unit,
)

@Composable
private fun MergeMerchantCatalogDialog(
    state: MerchantCatalogMergeDialogState,
    actions: MerchantCatalogMergeDialogActions,
) {
    AlertDialog(
        onDismissRequest = { if (!state.busy) actions.onDismiss() },
        title = { Text(stringResource(R.string.merchant_catalog_merge_dialog_title)) },
        text = {
            MergeMerchantCatalogDialogContent(
                state = state,
                actions = actions,
            )
        },
        confirmButton = {
            TextButton(
                enabled = !state.busy && !state.readOnly && !state.unavailable &&
                    state.selectedTarget != null && state.aliasPolicy != null,
                onClick = {
                    val target = state.selectedTarget ?: return@TextButton
                    val policy = state.aliasPolicy ?: return@TextButton
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

@Composable
private fun MergeMerchantCatalogDialogContent(
    state: MerchantCatalogMergeDialogState,
    actions: MerchantCatalogMergeDialogActions,
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
        state.selectedTarget?.let {
            Text(stringResource(R.string.merchant_merge_selected_target, it.displayName))
        }
        MerchantCatalogMergeTargetList(state.targets, state.selectedTarget, !state.busy && !state.readOnly, actions.onSelectTarget)
        MerchantCatalogAliasPolicySection(state.aliasPolicy, !state.busy && !state.readOnly, actions.onSelectAliasPolicy)
        AppStatusBanner(message = state.message, tone = state.messageTone)
        TextButton(enabled = !state.busy && state.selectedTarget != null, onClick = actions.onReview) {
            Text(stringResource(R.string.merchant_merge_review))
        }
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
