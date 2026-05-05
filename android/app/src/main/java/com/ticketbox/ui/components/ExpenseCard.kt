package com.ticketbox.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
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

    SoftPanel(containerAlpha = 0.96f) {
        Column(
            modifier = Modifier.padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                if (expense.imagePath != null) {
                    ExpenseImagePreview(
                        image = thumbnail,
                        placeholder = "截图",
                        compact = true,
                    )
                } else {
                    CategoryMark(expense.category)
                }
                Column(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text(
                        text = expense.merchant?.takeIf { it.isNotBlank() } ?: "待填写商家",
                        style = MaterialTheme.typography.titleMedium,
                        color = MaterialTheme.colorScheme.onSurface,
                        fontWeight = FontWeight.Black,
                    )
                    Text(
                        text = "${displayTime(expense.expenseTime ?: expense.confirmedAt ?: expense.createdAt)} · ${
                            if (expense.status == "pending") "截图待确认" else "已入账"
                        }",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Text(
                        text = expense.amountCents?.let(::formatAmount) ?: "等待你确认金额",
                        style = MaterialTheme.typography.titleLarge,
                        color = MaterialTheme.colorScheme.primary,
                        fontWeight = FontWeight.Black,
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        StatusPill(
                            text = expense.category,
                            active = true,
                        )
                        if (expense.amountCents == null) {
                            StatusPill(text = "待补金额", active = false)
                        } else if ((expense.confidence ?: 1.0) < 0.62) {
                            StatusPill(text = "请核对", active = false)
                        }
                        if (expense.duplicateStatus == "suspected") {
                            StatusPill(text = "疑似新账", active = false)
                        }
                    }
                }
            }

            expense.note?.takeIf { it.isNotBlank() }?.let {
                Text(
                    text = it,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            if (expense.imagePath != null && previewMode == ExpensePreviewMode.Comfortable) {
                val imagePlaceholder = if (expense.thumbnailPath != null) {
                    "截图缩略图加载中"
                } else {
                    "截图已保存，当前格式暂不预览"
                }
                ExpenseImagePreview(
                    image = thumbnail,
                    placeholder = imagePlaceholder,
                )
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
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    QuietOutlinedButton(
                        text = "编辑",
                        modifier = Modifier.weight(1f),
                        enabled = actionsEnabled,
                        onClick = onEdit,
                    )
                    if (showConfirmAction) {
                        Button(
                            modifier = Modifier.weight(1f),
                            enabled = actionsEnabled,
                            colors = ButtonDefaults.buttonColors(
                                containerColor = MaterialTheme.colorScheme.primary,
                                contentColor = MaterialTheme.colorScheme.onPrimary,
                            ),
                            onClick = onConfirm,
                        ) {
                            Text("入账")
                        }
                    }
                    if (showRejectAction) {
                        Spacer(Modifier.weight(0.15f))
                        OutlinedButton(
                            enabled = actionsEnabled,
                            onClick = { showRejectDialog = true },
                        ) {
                            Text("忽略")
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

@Composable
private fun CategoryMark(category: String) {
    Box(
        modifier = Modifier
            .size(54.dp)
            .clip(RoundedCornerShape(16.dp))
            .background(MaterialTheme.colorScheme.primaryContainer),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = category.take(1).ifBlank { "账" },
            color = MaterialTheme.colorScheme.primary,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Black,
            textAlign = TextAlign.Center,
        )
    }
}
