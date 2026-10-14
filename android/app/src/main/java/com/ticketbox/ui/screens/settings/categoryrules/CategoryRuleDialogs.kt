package com.ticketbox.ui.screens.settings.categoryrules

import androidx.compose.material3.AlertDialog
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.Modifier
import com.ticketbox.R
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.RuleApplicationBatch
import com.ticketbox.ui.components.AppBusyGuardedSheet
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.screens.settings.SettingsEntryRow

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
    application: RuleApplicationBatch,
    onDismiss: () -> Unit,
    onConfirm: () -> Unit,
) {
    AppBusyGuardedSheet(false, onDismiss, skipPartiallyExpanded = true) {
        AppSheetScaffold(title = stringResource(R.string.category_rule_rollback_dialog_title),
            subtitle = displayTime(application.createdAt), actions = {
                AppPrimaryButton(stringResource(R.string.category_rule_rollback_dialog_confirm), onClick = onConfirm,
                    modifier = Modifier.fillMaxWidth())
                TextButton(onClick = onDismiss, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.common_cancel)) }
            }) {
            SettingsEntryRow(stringResource(R.string.category_rule_rollback_original_count, application.changedCount),
                stringResource(R.string.category_rule_rollback_recheck), R.drawable.ic_lucide_receipt_text, onClick = null)
            SettingsEntryRow(stringResource(R.string.category_rule_impact_preserved),
                stringResource(R.string.category_rule_rollback_dialog_text), R.drawable.ic_lucide_shield_check, onClick = null)
        }
    }
}
