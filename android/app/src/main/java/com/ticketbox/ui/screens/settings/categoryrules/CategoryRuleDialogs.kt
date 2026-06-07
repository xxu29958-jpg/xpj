package com.ticketbox.ui.screens.settings.categoryrules

import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.RuleApplicationBatch

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
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.category_rule_rollback_dialog_title)) },
        text = { Text(stringResource(R.string.category_rule_rollback_dialog_text)) },
        confirmButton = {
            TextButton(onClick = onConfirm) {
                Text(stringResource(R.string.category_rule_rollback_dialog_confirm), color = MaterialTheme.colorScheme.error)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text(stringResource(R.string.common_cancel))
            }
        },
    )
}
