package com.ticketbox.ui.screens.settings.categoryrules

import androidx.compose.material3.AlertDialog
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.Modifier
import com.ticketbox.R
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.RuleApplicationRollbackPreview
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppBusyGuardedSheet
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputDecorations
import com.ticketbox.ui.screens.settings.SettingsEntryRow
import com.ticketbox.ui.screens.settings.CategoryRuleRollbackActions
import com.ticketbox.ui.screens.settings.CategoryRulesInteractionState
import com.ticketbox.viewmodel.RuleRollbackState

@Composable
internal fun DeleteCategoryRuleDialog(
    rule: CategoryRule,
    onDismiss: () -> Unit,
    onConfirm: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.category_rule_delete_dialog_title)) },
        text = { Text(stringResource(R.string.category_rule_delete_dialog_text, rule.keyword)) },
        confirmButton = {
            TextButton(onClick = onConfirm) {
                Text(stringResource(R.string.category_rule_delete_dialog_confirm), color = MaterialTheme.colorScheme.error)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text(stringResource(R.string.common_cancel))
            }
        },
    )
}

@Composable
internal fun RollbackRuleApplicationDialog(
    state: RuleRollbackState,
    interaction: CategoryRulesInteractionState,
    actions: CategoryRuleRollbackActions,
) {
    val application = state.application ?: return
    val verifying = state.submittedReason != null
    AppBusyGuardedSheet(interaction.busy, actions.onDismiss, skipPartiallyExpanded = true) {
        AppSheetScaffold(title = stringResource(R.string.category_rule_rollback_dialog_title),
            subtitle = displayTime(application.createdAt), actions = { RuleRollbackFooter(state, interaction, actions) }) {
            AppStatusBanner(state.error, MessageTone.Danger)
            if (verifying) AppStatusBanner(UiText.res(R.string.category_rule_rollback_original_pending), MessageTone.Info)
            if (state.loading) Text(stringResource(R.string.category_rule_rollback_loading))
            state.preview?.let { RuleRollbackPreviewDetails(it) }
            if (!verifying) TextButton(onClick = actions.onRefresh, enabled = !interaction.busy && !state.loading) {
                Text(stringResource(R.string.category_rule_impact_refresh))
            }
            AppTextInput(AppTextInputState(label = stringResource(R.string.category_rule_rollback_reason),
                value = state.reason, placeholder = stringResource(R.string.category_rule_rollback_reason_hint),
                singleLine = false, minLines = 2, enabled = !interaction.busy,
                readOnly = interaction.readOnly || verifying), AppTextInputActions(actions.onReasonChange),
                decorations = AppTextInputDecorations(supportingText = {
                    Text(stringResource(R.string.category_rule_reason_retained, state.reason.length))
                }))
            SettingsEntryRow(stringResource(R.string.category_rule_impact_preserved),
                stringResource(R.string.category_rule_rollback_recheck), R.drawable.ic_lucide_shield_check, onClick = null)
        }
    }
}

@Composable
private fun RuleRollbackFooter(state: RuleRollbackState, interaction: CategoryRulesInteractionState,
    actions: CategoryRuleRollbackActions,
) {
    val verifying = state.submittedReason != null
    val eligibleCount = state.preview?.eligibleCount ?: 0
    AppPrimaryButton(if (verifying) stringResource(R.string.category_rule_rollback_verify)
        else stringResource(R.string.category_rule_rollback_eligible_action, eligibleCount),
        enabled = !interaction.busy && !interaction.readOnly && !state.loading && (verifying || eligibleCount > 0),
        onClick = actions.onConfirm, modifier = Modifier.fillMaxWidth())
    TextButton(onClick = actions.onDismiss, enabled = !interaction.busy,
        modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.common_cancel)) }
}

@Composable
private fun RuleRollbackPreviewDetails(preview: RuleApplicationRollbackPreview) {
    SettingsEntryRow(stringResource(R.string.category_rule_rollback_original_count, preview.originalCount),
        stringResource(R.string.category_rule_rollback_counts, preview.eligibleCount, preview.skippedCount),
        R.drawable.ic_lucide_receipt_text, onClick = null)
    if (preview.eligibleCount == 0) Text(stringResource(R.string.category_rule_rollback_none))
    if (preview.skippedItems.isNotEmpty()) {
        var expanded by rememberSaveable(preview.publicId) { mutableStateOf(false) }
        SettingsEntryRow(stringResource(R.string.category_rule_rollback_retained_details, preview.skippedCount),
            stringResource(R.string.category_rule_rollback_retained_hint), R.drawable.ic_lucide_shield_check,
            onClick = { expanded = !expanded })
        if (expanded) preview.skippedItems.forEach { item ->
            SettingsEntryRow("${item.merchant ?: stringResource(R.string.category_rule_apply_preview_no_merchant)} · #${item.expenseId}",
                stringResource(when (item.reason) {
                    "modified_after_application" -> R.string.category_rule_rollback_modified
                    "already_rolled_back" -> R.string.category_rule_rollback_already_restored
                    "already_skipped" -> R.string.category_rule_rollback_already_skipped
                    "expense_unavailable" -> R.string.category_rule_rollback_unavailable
                    else -> R.string.category_rule_rollback_finished
                }), R.drawable.ic_lucide_receipt_text, onClick = null)
        }
    }
}
