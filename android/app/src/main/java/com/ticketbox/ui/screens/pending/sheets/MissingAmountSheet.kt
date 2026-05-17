package com.ticketbox.ui.screens.pending.sheets

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.formatMinorAmountInput
import com.ticketbox.ui.components.parseMinorAmount
import com.ticketbox.ui.design.AppTextHierarchy

/**
 * MissingAmount BottomSheet — slice 3 M4。
 * 金额输入以原始币种显示，提交后由后端计算入账金额。
 * 「保存草稿」走 updateExpense，「保存并确认」走 updateExpense + confirmExpense。
 * 不允许负数；空值不可确认；不直接写 confirmed。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun MissingAmountSheetContent(
    expense: Expense,
    saving: Boolean,
    onSaveDraft: (Long) -> Unit,
    onSaveAndConfirm: (Long) -> Unit,
    onDismiss: () -> Unit,
) {
    val currency = expense.originalCurrencyCode
    var input by remember(expense.id) {
        mutableStateOf(formatMinorAmountInput(expense.originalAmountMinor ?: expense.amountCents, currency))
    }
    val originalMinor = parseMinorAmount(input, currency)
    val invalid = input.isNotBlank() && (originalMinor == null || originalMinor <= 0)
    val canSave = originalMinor != null && originalMinor > 0 && !saving

    Column(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 18.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("补一下金额", style = MaterialTheme.typography.titleLarge, fontWeight = AppTextHierarchy.heading.weight)
        Text(
            text = "金额按原始币种输入，例如 12.34。保存后由后端按消费时间计算入账金额。",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )

        OutlinedTextField(
            value = input,
            onValueChange = { raw ->
                input = raw
                    .filter { c -> c.isDigit() || (!currency.noFractionDigits && c == '.') }
                    .take(12)
            },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            label = { Text("金额 (${currency.storageKey})") },
            placeholder = { Text(if (currency.noFractionDigits) "例如 1200" else "例如 12.34") },
            modifier = Modifier.fillMaxWidth(),
            enabled = !saving,
            isError = invalid,
            supportingText = if (invalid) {
                { Text("请输入大于 0 的金额", color = MaterialTheme.colorScheme.error) }
            } else null,
        )

        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            AppSecondaryButton(
                text = "取消",
                modifier = Modifier.weight(1f),
                enabled = !saving,
                onClick = onDismiss,
            )
            AppSecondaryButton(
                text = if (saving) "保存中" else "仅保存",
                modifier = Modifier.weight(1f),
                enabled = canSave,
                onClick = { originalMinor?.let(onSaveDraft) },
            )
            Button(
                modifier = Modifier.weight(1.2f),
                enabled = canSave,
                onClick = { originalMinor?.let(onSaveAndConfirm) },
            ) {
                Text(if (saving) "处理中" else "保存并确认")
            }
        }

        Text(
            text = "保存并确认会先 PATCH 金额，再调 /confirm。任何失败都不会绕过 amount_required。",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
        )
    }
}
