package com.ticketbox.ui.screens.pending.sheets

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalCurrencyDisplay

/**
 * DuplicateConfirmSheet — slice 3 M6。
 *
 * 三选一：
 *  - 保留两笔（markNotDuplicate）
 *  - 忽略当前（rejectExpense）
 *  - 取消
 *
 * 严格不自动删除、不静默确认。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun DuplicateConfirmSheetContent(
    expense: Expense,
    inProgress: Boolean,
    onKeepBoth: () -> Unit,
    onIgnoreCurrent: () -> Unit,
    onDismiss: () -> Unit,
) {
    val currencyDisplay = LocalCurrencyDisplay.current

    Column(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 18.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("处理疑似重复", style = MaterialTheme.typography.titleLarge, fontWeight = AppTextHierarchy.heading.weight)
        Text(
            text = "请你来决定。我们不会自动删除，也不会自动确认入账。",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )

        AppGlassCard(containerAlpha = 0.94f) {
            Column(
                modifier = Modifier.padding(horizontal = 14.dp, vertical = 12.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                Text(
                    text = expense.merchant?.takeIf { it.isNotBlank() } ?: "未填写商家",
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = AppTextHierarchy.body.weight,
                )
                Text(
                    text = formatDisplayAmount(expense.amountCents, currencyDisplay),
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = AppTextHierarchy.body.weight,
                )
                expense.duplicateReason?.takeIf { it.isNotBlank() }?.let {
                    Text(
                        text = "可能原因：$it",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
        }

        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(
                modifier = Modifier.fillMaxWidth(),
                enabled = !inProgress,
                onClick = onKeepBoth,
            ) { Text(if (inProgress) "处理中…" else "保留两笔（不是重复）") }
            AppSecondaryButton(
                text = if (inProgress) "处理中…" else "忽略当前（删除这条）",
                modifier = Modifier.fillMaxWidth(),
                enabled = !inProgress,
                onClick = onIgnoreCurrent,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                AppSecondaryButton(
                    text = "取消",
                    modifier = Modifier.fillMaxWidth(),
                    enabled = !inProgress,
                    onClick = onDismiss,
                )
            }
        }
    }
}
