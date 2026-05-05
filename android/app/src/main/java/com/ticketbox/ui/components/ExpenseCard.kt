package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ProtectedImage

enum class ExpensePreviewMode {
    Compact,
    Comfortable,
}

@Composable
fun ExpenseCard(
    expense: Expense,
    thumbnail: ProtectedImage? = null,
    previewMode: ExpensePreviewMode = ExpensePreviewMode.Comfortable,
    showActions: Boolean,
    showConfirmAction: Boolean = showActions,
    showRejectAction: Boolean = showActions,
    showDuplicateAction: Boolean = showActions,
    actionsEnabled: Boolean = true,
    onEdit: () -> Unit = {},
    onConfirm: () -> Unit = {},
    onReject: () -> Unit = {},
    onKeepDuplicate: () -> Unit = {},
) {
    var showRejectDialog by remember(expense.id) { mutableStateOf(false) }

    if (showRejectDialog) {
        AlertDialog(
            onDismissRequest = { if (actionsEnabled) showRejectDialog = false },
            title = { Text("删除这笔待确认账单？") },
            text = { Text("删除后这张截图会标记为已拒绝，不会进入账本。") },
            confirmButton = {
                TextButton(
                    enabled = actionsEnabled,
                    onClick = {
                        showRejectDialog = false
                        onReject()
                    },
                ) {
                    Text("确定删除", color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(
                    enabled = actionsEnabled,
                    onClick = { showRejectDialog = false },
                ) {
                    Text("取消")
                }
            },
        )
    }

    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = MaterialTheme.shapes.medium,
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.Top,
            ) {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(
                        text = expense.merchant?.takeIf { it.isNotBlank() } ?: "待填写商家",
                        style = MaterialTheme.typography.titleMedium,
                    )
                    Text(
                        text = displayTime(expense.expenseTime ?: expense.confirmedAt ?: expense.createdAt),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Text(
                    text = formatAmount(expense.amountCents),
                    style = MaterialTheme.typography.titleLarge,
                    color = MaterialTheme.colorScheme.primary,
                )
            }

            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                AssistChip(onClick = {}, label = { Text(expense.category) })
                AssistChip(onClick = {}, label = { Text(expense.source) })
                if (expense.duplicateStatus == "suspected") {
                    AssistChip(onClick = {}, label = { Text("可能重复") })
                }
            }

            Text(
                text = expense.note?.takeIf { it.isNotBlank() } ?: "没有备注",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            if (expense.imagePath != null) {
                val imagePlaceholder = if (expense.thumbnailPath != null) {
                    "截图缩略图加载中"
                } else {
                    "截图已保存，当前格式暂不预览"
                }
                if (previewMode == ExpensePreviewMode.Compact) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        ExpenseImagePreview(
                            image = thumbnail,
                            placeholder = "截图",
                            compact = true,
                        )
                        Column(
                            modifier = Modifier.weight(1f),
                            verticalArrangement = Arrangement.spacedBy(6.dp),
                        ) {
                            Text(
                                text = imagePlaceholder,
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            OutlinedButton(
                                enabled = actionsEnabled,
                                onClick = onEdit,
                            ) {
                                Text("查看截图")
                            }
                        }
                    }
                } else {
                    ExpenseImagePreview(
                        image = thumbnail,
                        placeholder = imagePlaceholder,
                    )
                }
            }

            if (expense.duplicateStatus == "suspected") {
                DuplicateNotice(reason = expense.duplicateReason)
            }

            expense.tags?.takeIf { it.isNotBlank() }?.let {
                Text(
                    text = "标签：$it",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            if (showActions) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(
                        enabled = actionsEnabled,
                        onClick = onEdit,
                    ) {
                        Text("编辑")
                    }
                    if (showConfirmAction) {
                        Button(
                            enabled = actionsEnabled,
                            onClick = onConfirm,
                        ) {
                            Text("确认")
                        }
                    }
                    if (showRejectAction) {
                        OutlinedButton(
                            enabled = actionsEnabled,
                            onClick = { showRejectDialog = true },
                        ) {
                            Text("删除")
                        }
                    }
                }
                if (showDuplicateAction && expense.duplicateStatus == "suspected") {
                    OutlinedButton(
                        enabled = actionsEnabled,
                        onClick = onKeepDuplicate,
                    ) {
                        Text("不是重复，保留")
                    }
                }
            }
        }
    }
}
