package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ProtectedImage

@Composable
fun ExpenseCard(
    expense: Expense,
    thumbnail: ProtectedImage? = null,
    showActions: Boolean,
    onEdit: () -> Unit = {},
    onConfirm: () -> Unit = {},
    onReject: () -> Unit = {},
    onKeepDuplicate: () -> Unit = {},
) {
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
                    AssistChip(onClick = {}, label = { Text("疑似重复") })
                }
            }

            Text(
                text = expense.note?.takeIf { it.isNotBlank() } ?: "没有备注",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            if (expense.imagePath != null) {
                ExpenseImagePreview(
                    image = thumbnail,
                    placeholder = if (expense.thumbnailPath != null) {
                        "截图缩略图加载中"
                    } else {
                        "截图已保存，当前格式暂不预览"
                    },
                )
            }

            expense.duplicateReason?.takeIf { it.isNotBlank() }?.let {
                Text(
                    text = it,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
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
                    OutlinedButton(onClick = onEdit) {
                        Text("编辑")
                    }
                    Button(onClick = onConfirm) {
                        Text("确认")
                    }
                    OutlinedButton(onClick = onReject) {
                        Text("删除")
                    }
                }
                if (expense.duplicateStatus == "suspected") {
                    OutlinedButton(onClick = onKeepDuplicate) {
                        Text("仍然保留")
                    }
                }
            }
        }
    }
}
