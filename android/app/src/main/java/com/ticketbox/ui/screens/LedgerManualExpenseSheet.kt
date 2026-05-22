package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TimeInput
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.FxContract
import com.ticketbox.domain.model.normalizeExpenseCategory
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.ui.components.AppSolidCard
import com.ticketbox.ui.components.datePickerMillisToUtcIso
import com.ticketbox.ui.components.displayDateTime
import com.ticketbox.ui.components.nowUtcIso
import com.ticketbox.ui.components.parseMinorAmount
import com.ticketbox.ui.components.selectedDateMillisFromIso
import com.ticketbox.ui.components.selectedHourFromIso
import com.ticketbox.ui.components.selectedMinuteFromIso
import com.ticketbox.ui.components.timePickerToUtcIso
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.expense.ExpenseCurrencyFields

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ManualExpenseSheet(
    categories: List<String>,
    saving: Boolean,
    initialCurrency: CurrencyCode = FxContract.HomeCurrency,
    onCreate: (ExpenseDraft) -> Unit,
    onDismiss: () -> Unit,
) {
    var amountText by rememberSaveable { mutableStateOf("") }
    var currency by rememberSaveable(initialCurrency) { mutableStateOf(initialCurrency) }
    var merchant by rememberSaveable { mutableStateOf("") }
    var category by rememberSaveable { mutableStateOf("餐饮") }
    var note by rememberSaveable { mutableStateOf("") }
    var expenseTime by rememberSaveable { mutableStateOf(nowUtcIso()) }
    var message by rememberSaveable { mutableStateOf<String?>(null) }
    var showDatePicker by rememberSaveable { mutableStateOf(false) }
    var showTimePicker by rememberSaveable { mutableStateOf(false) }

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
            DatePicker(
                state = datePickerState,
                title = {
                    Text(
                        "选择日期",
                        modifier = Modifier.padding(start = 24.dp, end = 12.dp, top = 16.dp),
                    )
                },
            )
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

    fun draftOrMessage(): ExpenseDraft? {
        val originalMinor = parseMinorAmount(amountText, currency)
        if (originalMinor == null) {
            message = "请填写正确金额。"
            return null
        }
        return ExpenseDraft(
            amountCents = null,
            originalCurrencyCode = currency,
            originalAmountMinor = originalMinor,
            merchant = merchant.ifBlank { null },
            category = normalizeExpenseCategory(category),
            note = note,
            expenseTime = expenseTime.ifBlank { nowUtcIso() },
            tags = null,
            valueScore = null,
            regretScore = null,
        )
    }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .imePadding()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = AppSpacing.cardPaddingSmall, vertical = AppSpacing.contentGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        Text("手动记一笔", style = MaterialTheme.typography.titleLarge)
        Text(
            text = "适合现金、零散消费，保存后直接进入账本。",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
        ExpenseCurrencyFields(
            currency = currency,
            onCurrencyChange = {
                currency = it
            },
            originalAmountText = amountText,
            onOriginalAmountChange = { amountText = it },
            enabled = !saving,
        )
        OutlinedTextField(
            value = merchant,
            onValueChange = { merchant = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("商家") },
            placeholder = { Text("便利店") },
            singleLine = true,
        )
        OutlinedTextField(
            value = category,
            onValueChange = { category = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("分类") },
            singleLine = true,
        )
        if (categories.isNotEmpty()) {
            LazyRow(horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap)) {
                items(categories, key = { it }) { item ->
                    SelectableFilterChip(
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
        AppSolidCard {
            Column(
                modifier = Modifier.padding(AppSpacing.cardPaddingTight),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.chipGap),
            ) {
                Text("消费时间", style = MaterialTheme.typography.titleSmall)
                Text(displayDateTime(expenseTime), color = MaterialTheme.colorScheme.onSurfaceVariant)
                Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap)) {
                    AppOutlinedButton(onClick = { showDatePicker = true }) {
                        Text("选日期")
                    }
                    TextButton(onClick = { showTimePicker = true }) {
                        Text("选时间")
                    }
                    TextButton(onClick = { expenseTime = nowUtcIso() }) {
                        Text("现在")
                    }
                }
            }
        }
        message?.let {
            Text(it, color = MaterialTheme.colorScheme.secondary)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap)) {
            AppOutlinedButton(
                modifier = Modifier.weight(1f),
                onClick = onDismiss,
            ) {
                Text("取消")
            }
            Button(
                modifier = Modifier.weight(1f),
                enabled = !saving,
                onClick = {
                    val draft = draftOrMessage() ?: return@Button
                    onCreate(draft)
                },
            ) {
                Text(if (saving) "保存中" else "记入账本")
            }
        }
    }
}

@Composable
fun CategoryFilterRow(
    categories: List<String>,
    selectedCategory: String,
    onCategoryChange: (String) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
        Text(
            text = "分类",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelMedium,
        )
        LazyRow(horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap)) {
            item {
                SelectableFilterChip(
                    selected = selectedCategory.isBlank(),
                    label = "全部分类",
                    onClick = { onCategoryChange("") },
                )
            }
            items(categories, key = { it }) { category ->
                SelectableFilterChip(
                    selected = selectedCategory == category,
                    label = category,
                    onClick = { onCategoryChange(category) },
                )
            }
        }
    }
}

@Composable
fun SelectableFilterChip(
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
        selectedContainerColor = MaterialTheme.colorScheme.primary.copy(alpha = 0.22f),
    )
}
