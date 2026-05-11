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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.formatAmountInput
import com.ticketbox.ui.components.parseAmountCents

/**
 * MissingAmount BottomSheet — slice 3 M4。
 * 金额输入以元显示，提交时转 amount_cents。
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
    var input by remember(expense.id) { mutableStateOf(formatAmountInput(expense.amountCents)) }
    val cents = parseAmountCents(input)
    val invalid = input.isNotBlank() && (cents == null || cents <= 0)
    val canSave = cents != null && cents > 0 && !saving

    Column(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 18.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("补一下金额", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Black)
        Text(
            text = "金额按元为单位输入，例如 12.34。提交后会按 amount_cents 存储。",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )

        OutlinedTextField(
            value = input,
            onValueChange = { raw ->
                input = raw.filter { c -> c.isDigit() || c == '.' }.take(12)
            },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            label = { Text("金额 (元)") },
            placeholder = { Text("例如 12.34") },
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
                onClick = { cents?.let(onSaveDraft) },
            )
            Button(
                modifier = Modifier.weight(1.2f),
                enabled = canSave,
                onClick = { cents?.let(onSaveAndConfirm) },
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
