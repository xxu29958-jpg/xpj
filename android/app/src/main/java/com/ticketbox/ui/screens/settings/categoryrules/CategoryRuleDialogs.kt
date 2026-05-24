package com.ticketbox.ui.screens.settings.categoryrules

import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
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
        title = { Text("删除这条规则？") },
        text = { Text("删除后，后续识别不再参考“${rule.keyword}”。") },
        confirmButton = {
            TextButton(onClick = onConfirm) {
                Text("删除", color = MaterialTheme.colorScheme.error)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("取消")
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
        title = { Text("回退这次应用？") },
        text = { Text("会尽量恢复这次规则应用前的分类，已经手动改过的账单会跳过。") },
        confirmButton = {
            TextButton(onClick = onConfirm) {
                Text("回退", color = MaterialTheme.colorScheme.error)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("取消")
            }
        },
    )
}
