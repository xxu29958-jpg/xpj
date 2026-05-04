package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.ui.components.ExpenseImagePreview
import com.ticketbox.ui.components.formatAmountInput
import com.ticketbox.ui.components.parseAmountCents
import com.ticketbox.viewmodel.ExpenseEditUiState

@Composable
fun ExpenseEditScreen(
    expense: Expense,
    state: ExpenseEditUiState,
    onSave: (ExpenseDraft) -> Unit,
    onConfirm: (ExpenseDraft) -> Unit,
    onReject: () -> Unit,
    onRetryOcr: () -> Unit,
    onLoadFullImage: () -> Unit,
    onKeepDuplicate: () -> Unit,
    onDone: () -> Unit,
) {
    val currentExpense = state.expense ?: expense
    var amountText by remember(currentExpense.id, currentExpense.updatedAt) {
        mutableStateOf(formatAmountInput(currentExpense.amountCents))
    }
    var merchant by remember(currentExpense.id, currentExpense.updatedAt) { mutableStateOf(currentExpense.merchant.orEmpty()) }
    var category by remember(currentExpense.id, currentExpense.updatedAt) { mutableStateOf(currentExpense.category) }
    var note by remember(currentExpense.id, currentExpense.updatedAt) { mutableStateOf(currentExpense.note.orEmpty()) }
    var expenseTime by remember(currentExpense.id, currentExpense.updatedAt) {
        mutableStateOf(currentExpense.expenseTime.orEmpty())
    }
    var tags by remember(currentExpense.id, currentExpense.updatedAt) { mutableStateOf(currentExpense.tags.orEmpty()) }
    var valueScoreText by remember(currentExpense.id, currentExpense.updatedAt) {
        mutableStateOf(currentExpense.valueScore?.toString().orEmpty())
    }
    var regretScoreText by remember(currentExpense.id, currentExpense.updatedAt) {
        mutableStateOf(currentExpense.regretScore?.toString().orEmpty())
    }
    var message by remember { mutableStateOf<String?>(null) }
    var rawTextExpanded by remember(currentExpense.id) { mutableStateOf(false) }
    val rawTextDisplay = currentExpense.rawText?.takeIf { it.isNotBlank() } ?: "第一版为空"
    val previewImage = state.fullImage ?: state.thumbnail

    LaunchedEffect(state.done) {
        if (state.done) onDone()
    }

    fun parseScore(raw: String, label: String): Int? {
        if (raw.isBlank()) return null
        val score = raw.toIntOrNull()
        if (score == null || score !in 1..5) {
            message = "$label 只能填写 1 到 5。"
            return null
        }
        return score
    }

    fun draftOrMessage(): ExpenseDraft? {
        val cents = parseAmountCents(amountText)
        if (amountText.isNotBlank() && cents == null) {
            message = "金额格式不正确"
            return null
        }
        val valueScore = if (valueScoreText.isBlank()) null else (parseScore(valueScoreText, "值不值评分") ?: return null)
        val regretScore = if (regretScoreText.isBlank()) null else (parseScore(regretScoreText, "后悔指数") ?: return null)
        return ExpenseDraft(
            amountCents = cents,
            merchant = merchant.ifBlank { null },
            category = category.ifBlank { "其他" },
            note = note,
            expenseTime = expenseTime.ifBlank { null },
            tags = tags.ifBlank { null },
            valueScore = valueScore,
            regretScore = regretScore,
        )
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("编辑账单", style = MaterialTheme.typography.headlineSmall)

        if (currentExpense.imagePath != null) {
            ExpenseImagePreview(
                image = previewImage,
                placeholder = if (state.imageLoading) {
                    "截图加载中"
                } else {
                    "截图已保存，当前格式暂不预览"
                },
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = onLoadFullImage) {
                    Text(if (state.imageLoading) "加载中" else "查看原图")
                }
                if (currentExpense.duplicateStatus == "suspected") {
                    OutlinedButton(onClick = onKeepDuplicate) {
                        Text("仍然保留")
                    }
                }
            }
            currentExpense.duplicateReason?.takeIf { it.isNotBlank() }?.let {
                Text(it, color = MaterialTheme.colorScheme.error)
            }
        }

        OutlinedTextField(
            value = amountText,
            onValueChange = { amountText = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("金额，单位元") },
            placeholder = { Text("36.80") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            singleLine = true,
        )
        OutlinedTextField(
            value = merchant,
            onValueChange = { merchant = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("商家") },
            singleLine = true,
        )
        OutlinedTextField(
            value = category,
            onValueChange = { category = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("分类") },
            singleLine = true,
        )
        if (state.categories.isNotEmpty()) {
            LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                items(state.categories, key = { it }) { item ->
                    AssistChip(
                        onClick = { category = item },
                        label = { Text(item) },
                    )
                }
            }
        }
        OutlinedTextField(
            value = note,
            onValueChange = { note = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("备注") },
        )
        OutlinedTextField(
            value = tags,
            onValueChange = { tags = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("标签") },
            placeholder = { Text("真香、必要支出") },
        )
        OutlinedTextField(
            value = valueScoreText,
            onValueChange = { valueScoreText = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("值不值评分，1-5") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            singleLine = true,
        )
        OutlinedTextField(
            value = regretScoreText,
            onValueChange = { regretScoreText = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("后悔指数，1-5") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            singleLine = true,
        )
        OutlinedTextField(
            value = expenseTime,
            onValueChange = { expenseTime = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("消费时间，ISO 8601") },
            placeholder = { Text("2026-05-03T04:20:00Z") },
            singleLine = true,
        )
        Text("来源：${currentExpense.source}", color = MaterialTheme.colorScheme.onSurfaceVariant)
        currentExpense.confidence?.let {
            Text("识别置信度：${(it * 100).toInt()}%", color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            TextButton(onClick = { rawTextExpanded = !rawTextExpanded }) {
                Text(if (rawTextExpanded) "收起 OCR 原文" else "查看 OCR 原文")
            }
            OutlinedButton(onClick = onRetryOcr) {
                Text(if (state.ocrRunning) "识别中" else "重新识别")
            }
        }
        if (rawTextExpanded) {
            Text("OCR 原文：$rawTextDisplay", color = MaterialTheme.colorScheme.onSurfaceVariant)
        }

        message?.let {
            Text(it, color = MaterialTheme.colorScheme.secondary)
        }
        state.message?.let {
            Text(it, color = MaterialTheme.colorScheme.secondary)
        }

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = onDone) {
                Text("返回")
            }
            Button(
                onClick = {
                    val draft = draftOrMessage() ?: return@Button
                    onSave(draft)
                },
            ) {
                Text(if (state.saving) "保存中" else "保存")
            }
        }

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(
                onClick = {
                    val draft = draftOrMessage() ?: return@Button
                    if (draft.amountCents == null) {
                        message = "请先填写金额。"
                        return@Button
                    }
                    onConfirm(draft)
                },
            ) {
                Text("确认入账")
            }
            OutlinedButton(
                onClick = onReject,
            ) {
                Text("删除")
            }
        }
        Spacer(Modifier.height(24.dp))
    }
}
