package com.ticketbox.ui.screens

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TimeInput
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.DpSize
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.domain.model.normalizeExpenseCategory
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppPageScrollableColumn
import com.ticketbox.ui.components.DuplicateNotice
import com.ticketbox.ui.components.ExpenseImagePreview
import com.ticketbox.ui.components.datePickerMillisToUtcIso
import com.ticketbox.ui.components.displayDateTime
import com.ticketbox.ui.components.formatAmount
import com.ticketbox.ui.components.formatAmountInput
import com.ticketbox.ui.components.nowUtcIso
import com.ticketbox.ui.components.parseAmountCents
import com.ticketbox.ui.components.selectedDateMillisFromIso
import com.ticketbox.ui.components.selectedHourFromIso
import com.ticketbox.ui.components.selectedMinuteFromIso
import com.ticketbox.ui.components.SoftPanel
import com.ticketbox.ui.components.StatusPill
import com.ticketbox.ui.components.timePickerToUtcIso
import com.ticketbox.viewmodel.ExpenseEditUiState

@OptIn(ExperimentalMaterial3Api::class)
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
    allowConfirm: Boolean = true,
    allowReject: Boolean = true,
) {
    BackHandler {
        if (!state.saving) {
            onDone()
        }
    }

    val currentExpense = state.expense ?: expense
    var amountText by remember(currentExpense.id, currentExpense.updatedAt) {
        mutableStateOf(formatAmountInput(currentExpense.amountCents))
    }
    var merchant by remember(currentExpense.id, currentExpense.updatedAt) { mutableStateOf(currentExpense.merchant.orEmpty()) }
    var category by remember(currentExpense.id, currentExpense.updatedAt) {
        mutableStateOf(normalizeExpenseCategory(currentExpense.category))
    }
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
    var moreExpanded by remember(currentExpense.id) { mutableStateOf(false) }
    var showDatePicker by remember(currentExpense.id) { mutableStateOf(false) }
    var showTimePicker by remember(currentExpense.id) { mutableStateOf(false) }
    var showRejectDialog by remember(currentExpense.id) { mutableStateOf(false) }
    var showLargeImage by remember(currentExpense.id) { mutableStateOf(false) }
    val rawTextDisplay = currentExpense.rawText?.takeIf { it.isNotBlank() } ?: "第一版为空"
    val previewImage = state.fullImage ?: state.thumbnail

    if (showDatePicker) {
        val datePickerState = androidx.compose.material3.rememberDatePickerState(
            initialSelectedDateMillis = selectedDateMillisFromIso(expenseTime),
        )
        DatePickerDialog(
            onDismissRequest = { showDatePicker = false },
            confirmButton = {
                TextButton(
                    onClick = {
                        datePickerState.selectedDateMillis?.let { selected ->
                            expenseTime = datePickerMillisToUtcIso(selected, expenseTime)
                        }
                        showDatePicker = false
                    },
                ) {
                    Text("确定")
                }
            },
            dismissButton = {
                TextButton(onClick = { showDatePicker = false }) {
                    Text("取消")
                }
            },
        ) {
            DatePicker(state = datePickerState)
        }
    }

    if (showTimePicker) {
        val timePickerState = androidx.compose.material3.rememberTimePickerState(
            initialHour = selectedHourFromIso(expenseTime),
            initialMinute = selectedMinuteFromIso(expenseTime),
            is24Hour = true,
        )
        AlertDialog(
            onDismissRequest = { showTimePicker = false },
            title = { Text("选择时间") },
            text = { TimeInput(state = timePickerState) },
            confirmButton = {
                TextButton(
                    onClick = {
                        expenseTime = timePickerToUtcIso(
                            hour = timePickerState.hour,
                            minute = timePickerState.minute,
                            currentIso = expenseTime,
                        )
                        showTimePicker = false
                    },
                ) {
                    Text("确定")
                }
            },
            dismissButton = {
                TextButton(onClick = { showTimePicker = false }) {
                    Text("取消")
                }
            },
        )
    }

    if (showRejectDialog) {
        AlertDialog(
            onDismissRequest = { showRejectDialog = false },
            title = { Text("删除这笔账单？") },
            text = { Text("删除后会标记为已拒绝，不会进入账本。") },
            confirmButton = {
                TextButton(
                    onClick = {
                        showRejectDialog = false
                        onReject()
                    },
                ) {
                    Text("确定删除", color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(onClick = { showRejectDialog = false }) {
                    Text("取消")
                }
            },
        )
    }

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
            category = normalizeExpenseCategory(category),
            note = note,
            expenseTime = expenseTime.ifBlank { null },
            tags = tags.ifBlank { null },
            valueScore = valueScore,
            regretScore = regretScore,
        )
    }

    AppPageScrollableColumn(
        role = AppPageRole.Edit,
        hasBottomBar = false,
        includeStatusBarPadding = true,
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
            AppPageHeader(
                title = "确认账单",
                subtitle = "识别只是草稿，补全后再正式入账",
                eyebrow = "",
            ) {
                StatusPill(if (currentExpense.status == "pending") "待确认" else "已入账")
            }

            EditDraftPreviewCard(
                expense = currentExpense,
                previewImage = previewImage,
                imageLoading = state.imageLoading,
                ocrRunning = state.ocrRunning,
                showLargeImage = showLargeImage,
                onToggleLargeImage = {
                    if (!showLargeImage && state.fullImage == null) {
                        onLoadFullImage()
                    }
                    showLargeImage = !showLargeImage
                },
                onRetryOcr = onRetryOcr,
            )

            if (showLargeImage && currentExpense.imagePath != null) {
                ExpenseImagePreview(
                    image = state.fullImage ?: previewImage,
                    placeholder = if (state.imageLoading) {
                        "原图加载中"
                    } else {
                        "原图暂时加载失败，截图已保存"
                    },
                    displayHeight = 420.dp,
                )
            }

            if (currentExpense.duplicateStatus == "suspected") {
                DuplicateNotice(reason = currentExpense.duplicateReason)
                OutlinedButton(onClick = onKeepDuplicate) {
                    Text("不是重复，保留")
                }
            }

            AnimatedVisibility(visible = state.ocrRunning) {
                OcrProgressCard()
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
                    SelectableCategoryChip(
                        selected = category == item,
                        label = item,
                        onClick = { category = item },
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
        ExpenseDateField(
            expenseTime = expenseTime,
            onPickDate = { showDatePicker = true },
            onPickTime = { showTimePicker = true },
            onUseNow = { expenseTime = nowUtcIso() },
            onClear = { expenseTime = "" },
        )
        Text("来源：${currentExpense.source}", color = MaterialTheme.colorScheme.onSurfaceVariant)
        currentExpense.confidence?.let {
            Text("识别置信度：${(it * 100).toInt()}%", color = MaterialTheme.colorScheme.onSurfaceVariant)
        }

        SoftPanel(containerAlpha = 0.98f) {
            Column(
                modifier = Modifier.padding(12.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                        Text("更多记录", style = MaterialTheme.typography.titleSmall)
                        Text(
                            text = "标签、值不值、后悔指数和识别原文",
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                    OutlinedButton(onClick = { moreExpanded = !moreExpanded }) {
                        Text(if (moreExpanded) "收起" else "展开")
                    }
                }

                if (moreExpanded) {
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
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        TextButton(onClick = { rawTextExpanded = !rawTextExpanded }) {
                            Text(if (rawTextExpanded) "收起识别原文" else "查看识别原文")
                        }
                        OutlinedButton(
                            enabled = !state.ocrRunning && !state.saving,
                            onClick = onRetryOcr,
                        ) {
                            Text(if (state.ocrRunning) "识别中" else "重新识别")
                        }
                    }
                    if (rawTextExpanded) {
                        Text("识别原文：$rawTextDisplay", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }

        message?.let {
            Text(it, color = MaterialTheme.colorScheme.secondary)
        }
        state.message?.let {
            Text(it, color = MaterialTheme.colorScheme.secondary)
        }

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            OutlinedButton(
                modifier = Modifier.weight(1f),
                enabled = !state.saving,
                onClick = onDone,
            ) {
                Text("返回")
            }
            Button(
                modifier = Modifier.weight(1f),
                enabled = !state.saving,
                onClick = {
                    val draft = draftOrMessage() ?: return@Button
                    onSave(draft)
                },
            ) {
                Text(if (state.saving) "保存中" else "保存")
            }
        }

        if (allowConfirm || allowReject) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                if (allowConfirm) {
                    Button(
                        modifier = Modifier.weight(1f),
                        enabled = !state.saving,
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
                }
                if (allowReject) {
                    OutlinedButton(
                        modifier = Modifier.weight(if (allowConfirm) 0.72f else 1f),
                        enabled = !state.saving,
                        colors = ButtonDefaults.outlinedButtonColors(
                            contentColor = MaterialTheme.colorScheme.error,
                        ),
                        onClick = { showRejectDialog = true },
                    ) {
                        Text("删除")
                    }
                }
            }
        }
    }
}


@Composable
private fun EditDraftPreviewCard(
    expense: Expense,
    previewImage: ProtectedImage?,
    imageLoading: Boolean,
    ocrRunning: Boolean,
    showLargeImage: Boolean,
    onToggleLargeImage: () -> Unit,
    onRetryOcr: () -> Unit,
) {
    SoftPanel(containerAlpha = 0.98f) {
        Row(
            modifier = Modifier.padding(14.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
        ) {
            if (expense.imagePath != null) {
                ExpenseImagePreview(
                    image = previewImage,
                    placeholder = if (imageLoading) "截图加载中" else "截图已保存",
                    compact = true,
                    compactSize = DpSize(width = 104.dp, height = 136.dp),
                )
            }
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(7.dp),
            ) {
                Text(
                    text = "识别草稿",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelLarge,
                )
                Text(
                    text = expense.merchant?.takeIf { it.isNotBlank() } ?: "待填写商家",
                    style = MaterialTheme.typography.titleLarge,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Text(
                    text = formatAmount(expense.amountCents),
                    style = MaterialTheme.typography.headlineMedium,
                    color = MaterialTheme.colorScheme.primary,
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    StatusPill(expense.category)
                    expense.confidence?.let {
                        StatusPill("可信度 ${(it * 100).toInt()}%", active = false)
                    }
                }
                if (expense.imagePath != null) {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(
                            modifier = Modifier
                                .weight(0.82f)
                                .height(40.dp),
                            enabled = !imageLoading,
                            contentPadding = PaddingValues(horizontal = 8.dp, vertical = 0.dp),
                            onClick = onToggleLargeImage,
                        ) {
                            Text(
                                when {
                                    imageLoading -> "加载中"
                                    showLargeImage -> "收起截图"
                                    else -> "看原图"
                                },
                                maxLines = 1,
                                softWrap = false,
                                overflow = TextOverflow.Ellipsis,
                                style = MaterialTheme.typography.labelMedium,
                                fontWeight = FontWeight.Bold,
                            )
                        }
                        OutlinedButton(
                            modifier = Modifier
                                .weight(1f)
                                .height(40.dp),
                            enabled = !ocrRunning,
                            contentPadding = PaddingValues(horizontal = 8.dp, vertical = 0.dp),
                            onClick = onRetryOcr,
                        ) {
                            Text(
                                if (ocrRunning) "识别中" else "重新识别",
                                maxLines = 1,
                                softWrap = false,
                                overflow = TextOverflow.Ellipsis,
                                style = MaterialTheme.typography.labelMedium,
                                fontWeight = FontWeight.Bold,
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun OcrProgressCard() {
    SoftPanel(containerAlpha = 0.98f) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(
                text = "正在重新识别截图",
                style = MaterialTheme.typography.titleMedium,
            )
            Text(
                text = "识别结果只会更新草稿，仍需要你核对后确认入账。",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
            LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
        }
    }
}

@Composable
private fun SelectableCategoryChip(
    selected: Boolean,
    label: String,
    onClick: () -> Unit,
) {
    AppFilterChip(
        selected = selected,
        onClick = onClick,
        label = label,
        leadingIcon = if (selected) {
            {
                Icon(
                    imageVector = Icons.Filled.Check,
                    contentDescription = null,
                    modifier = Modifier.size(FilterChipDefaults.IconSize),
                )
            }
        } else {
            null
        },
    )
}

@Composable
private fun ExpenseDateField(
    expenseTime: String,
    onPickDate: () -> Unit,
    onPickTime: () -> Unit,
    onUseNow: () -> Unit,
    onClear: () -> Unit,
) {
    SoftPanel(containerAlpha = 0.98f) {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                    Text("消费时间", style = MaterialTheme.typography.titleSmall)
                    Text(
                        text = displayDateTime(expenseTime),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                OutlinedButton(onClick = onPickDate) {
                    Text("选日期")
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TextButton(onClick = onPickTime) {
                    Text("选时间")
                }
                TextButton(onClick = onUseNow) {
                    Text("设为现在")
                }
                TextButton(
                    enabled = expenseTime.isNotBlank(),
                    onClick = onClear,
                ) {
                    Text("清除")
                }
            }
        }
    }
}
