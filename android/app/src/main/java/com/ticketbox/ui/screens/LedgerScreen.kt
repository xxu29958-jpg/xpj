package com.ticketbox.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.automirrored.filled.ReceiptLong
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TimeInput
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.normalizeExpenseCategory
import com.ticketbox.ui.components.AppEmptyStateCard
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.MonthPickerSheet
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.SoftPanel
import com.ticketbox.ui.components.datePickerMillisToUtcIso
import com.ticketbox.ui.components.displayDateTime
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.components.formatAmount
import com.ticketbox.ui.components.nowUtcIso
import com.ticketbox.ui.components.parseAmountCents
import com.ticketbox.ui.components.selectedDateMillisFromIso
import com.ticketbox.ui.components.selectedHourFromIso
import com.ticketbox.ui.components.selectedMinuteFromIso
import com.ticketbox.ui.components.timePickerToUtcIso
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.viewmodel.LedgerUiState
import java.time.Instant
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LedgerScreen(
    state: LedgerUiState,
    onMonthChange: (String) -> Unit,
    onCategoryChange: (String) -> Unit,
    onQueryChange: (String) -> Unit,
    onClearFilters: () -> Unit,
    onSync: () -> Unit,
    onExportCsv: () -> Unit,
    onManualCreate: (ExpenseDraft) -> Unit,
    onEdit: (Expense) -> Unit,
) {
    var showMonthPicker by rememberSaveable { mutableStateOf(false) }
    var showManualSheet by rememberSaveable { mutableStateOf(false) }
    var showLedgerTools by rememberSaveable { mutableStateOf(false) }
    val canExport = state.items.isNotEmpty() && !state.exporting

    if (showMonthPicker) {
        ModalBottomSheet(onDismissRequest = { showMonthPicker = false }) {
            MonthPickerSheet(
                months = state.months,
                selectedMonth = state.monthFilter,
                description = "选择后会刷新账本。历史月份多了以后可以上下滑动。",
                onSelectMonth = { month ->
                    onMonthChange(month)
                    showMonthPicker = false
                },
            )
        }
    }

    if (showManualSheet) {
        ModalBottomSheet(onDismissRequest = { showManualSheet = false }) {
            ManualExpenseSheet(
                categories = state.categories,
                saving = state.creatingManual,
                onCreate = { draft ->
                    showManualSheet = false
                    onManualCreate(draft)
                },
                onDismiss = { showManualSheet = false },
            )
        }
    }

    if (showLedgerTools) {
        ModalBottomSheet(onDismissRequest = { showLedgerTools = false }) {
            LedgerToolsSheet(
                state = state,
                canExport = canExport,
                onCategoryChange = onCategoryChange,
                onQueryChange = onQueryChange,
                onClearFilters = onClearFilters,
                onSync = onSync,
                onExportCsv = onExportCsv,
                onDismiss = { showLedgerTools = false },
            )
        }
    }

    val groupedItems = remember(state.items) { groupLedgerExpenses(state.items) }

    AppScrollableContent(
        role = AppPageRole.Ledger,
        isRefreshing = state.syncing,
        onRefresh = onSync,
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            LedgerFilterPanel(
                state = state,
                onOpenMonthPicker = { showMonthPicker = true },
                onOpenTools = { showLedgerTools = true },
                onManualAdd = { showManualSheet = true },
                onCategoryChange = onCategoryChange,
            )
        }
        if (state.items.isEmpty()) {
            item {
                EmptyLedgerState(
                    state = state,
                    onClearFilters = onClearFilters,
                    onSync = onSync,
                    onManualAdd = { showManualSheet = true },
                )
            }
        }
        groupedItems.forEach { group ->
            item(key = "ledger-day-${group.key}") {
                LedgerDayHeader(group.label)
            }
            items(group.items, key = { it.id }) { expense ->
                LedgerExpenseCard(
                    expense = expense,
                    onEdit = { onEdit(expense) },
                )
            }
        }
    }
}

@Composable
private fun LedgerFilterPanel(
    state: LedgerUiState,
    onOpenMonthPicker: () -> Unit,
    onOpenTools: () -> Unit,
    onManualAdd: () -> Unit,
    onCategoryChange: (String) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        LedgerHeader(onManualAdd = onManualAdd)
        LedgerSummaryStrip(state)
        LedgerInlineFilters(
            state = state,
            onOpenMonthPicker = onOpenMonthPicker,
            onOpenTools = onOpenTools,
            onCategoryChange = onCategoryChange,
        )
        Text(
            text = ledgerCombinedStatusLine(state),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
            fontWeight = FontWeight.Medium,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun LedgerInlineFilters(
    state: LedgerUiState,
    onOpenMonthPicker: () -> Unit,
    onOpenTools: () -> Unit,
    onCategoryChange: (String) -> Unit,
) {
    val hasQuery = state.query.isNotBlank()
    val quickCategories = remember(state.categories) { state.categories.take(2) }
    val selectedOutsideQuick = state.categoryFilter.isNotBlank() && state.categoryFilter !in quickCategories
    LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        item {
            AppFilterChip(
                selected = true,
                onClick = onOpenMonthPicker,
                label = displayMonthLabel(state.monthFilter).takeIf { state.monthFilter.isNotBlank() } ?: "全部月份",
                trailingIcon = {
                    Icon(
                        imageVector = Icons.Filled.ExpandMore,
                        contentDescription = "选择月份",
                        modifier = Modifier.size(FilterChipDefaults.IconSize),
                    )
                },
            )
        }
        item {
            SelectableFilterChip(
                selected = state.categoryFilter.isBlank(),
                label = "全部分类",
                onClick = { onCategoryChange("") },
            )
        }
        items(quickCategories, key = { it }) { category ->
            SelectableFilterChip(
                selected = state.categoryFilter == category,
                label = category,
                onClick = { onCategoryChange(category) },
            )
        }
        item {
            AppFilterChip(
                selected = hasQuery,
                onClick = onOpenTools,
                label = if (hasQuery) "已搜索" else "搜索备注",
                leadingIcon = if (hasQuery) {
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
        item {
            AppFilterChip(
                selected = selectedOutsideQuick,
                onClick = onOpenTools,
                label = if (selectedOutsideQuick) state.categoryFilter else "更多",
            )
        }
    }
}

@Composable
private fun LedgerToolsSheet(
    state: LedgerUiState,
    canExport: Boolean,
    onCategoryChange: (String) -> Unit,
    onQueryChange: (String) -> Unit,
    onClearFilters: () -> Unit,
    onSync: () -> Unit,
    onExportCsv: () -> Unit,
    onDismiss: () -> Unit,
) {
    val hasUserFilters = state.categoryFilter.isNotBlank() || state.query.isNotBlank()
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 18.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text("筛选与同步", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Black)
            Text(
                text = ledgerCombinedStatusLine(state),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        CategoryFilterRow(
            categories = state.categories,
            selectedCategory = state.categoryFilter,
            onCategoryChange = onCategoryChange,
        )
        OutlinedTextField(
            value = state.query,
            onValueChange = onQueryChange,
            modifier = Modifier
                .fillMaxWidth()
                .height(52.dp),
            placeholder = { Text("搜索备注") },
            singleLine = true,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            LedgerInlineButton(
                text = if (state.exporting) "导出中" else "导出 CSV",
                modifier = Modifier.weight(1f),
                enabled = canExport,
                onClick = onExportCsv,
            )
            LedgerInlineButton(
                text = if (state.syncing) "同步中" else "同步账本",
                modifier = Modifier.weight(1f),
                enabled = !state.syncing,
                onClick = onSync,
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            if (hasUserFilters) {
                QuietOutlinedButton(
                    text = "清除筛选",
                    modifier = Modifier.weight(1f),
                    onClick = onClearFilters,
                )
            }
            Button(
                modifier = Modifier.weight(1f),
                onClick = onDismiss,
            ) {
                Text("完成")
            }
        }
        if (state.items.isEmpty()) {
            Text(
                text = "当前没有可导出的已确认账单。",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun LedgerInlineButton(
    text: String,
    modifier: Modifier,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    OutlinedButton(
        modifier = modifier.heightIn(min = 40.dp),
        enabled = enabled,
        onClick = onClick,
        contentPadding = PaddingValues(horizontal = 10.dp, vertical = 0.dp),
    ) {
        Text(
            text = text,
            maxLines = 1,
            softWrap = false,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun LedgerHeader(onManualAdd: () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(0.dp)) {
        Text(
            text = "小票夹",
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.onBackground,
            fontWeight = FontWeight.Black,
        )
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                Text(
                    text = "账本",
                    style = MaterialTheme.typography.titleLarge,
                    color = MaterialTheme.colorScheme.onBackground,
                    fontWeight = FontWeight.Black,
                    maxLines = 1,
                )
                Text(
                    text = "已确认支出 · 可离线查看",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodyMedium,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Button(
                modifier = Modifier.heightIn(min = 44.dp),
                onClick = onManualAdd,
                contentPadding = PaddingValues(horizontal = 16.dp, vertical = 0.dp),
            ) {
                Icon(Icons.Filled.Add, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(6.dp))
                Text("记一笔")
            }
        }
    }
}

@Composable
private fun LedgerSummaryStrip(state: LedgerUiState) {
    val total = state.items.sumOf { it.amountCents ?: 0L }
    SoftPanel(containerAlpha = 0.98f) {
        Column(
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(16.dp),
                verticalAlignment = Alignment.Bottom,
            ) {
                Column(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(2.dp),
                ) {
                    Text(
                        text = "${displayMonthLabel(state.monthFilter)} 合计",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.titleSmall,
                    )
                    Text(
                        text = formatAmount(total),
                        color = MaterialTheme.colorScheme.primary,
                        style = MaterialTheme.typography.headlineSmall,
                        fontWeight = FontWeight.Black,
                    )
                }
                Column(
                    modifier = Modifier.weight(1f),
                    horizontalAlignment = Alignment.End,
                    verticalArrangement = Arrangement.spacedBy(2.dp),
                ) {
                    Text(
                        text = "账单",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.labelMedium,
                        textAlign = TextAlign.End,
                    )
                    Text(
                        text = "${state.items.size} 笔",
                        color = MaterialTheme.colorScheme.onSurface,
                        style = MaterialTheme.typography.titleMedium,
                        textAlign = TextAlign.End,
                    )
                }
            }
            LedgerSummaryTrendDots(state.items)
        }
    }
}

@Composable
private fun LedgerSummaryTrendDots(items: List<Expense>) {
    val visuals = LocalThemeVisuals.current
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(7.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        val amounts = items.take(10).map { it.amountCents ?: 0L }
        val maxAmount = amounts.maxOrNull()?.takeIf { it > 0L } ?: 1L
        val sample = if (amounts.isEmpty()) {
            List(10) { 0L }
        } else {
            amounts + List((10 - amounts.size).coerceAtLeast(0)) { 0L }
        }
        sample.take(10).forEach { amount ->
            val width = if (amount > 0L) {
                (18 + 18 * (amount.toFloat() / maxAmount.toFloat()).coerceIn(0f, 1f)).dp
            } else {
                18.dp
            }
            Box(
                modifier = Modifier
                    .width(width)
                    .height(6.dp)
                    .clip(RoundedCornerShape(999.dp))
                    .background(
                        if (amount > 0L) {
                            visuals.primary.copy(alpha = 0.72f)
                        } else {
                            visuals.chipUnselected.copy(alpha = 0.70f)
                        },
                    ),
            )
        }
    }
}

@Composable
private fun LedgerDayHeader(label: String) {
    Text(
        text = label,
        color = MaterialTheme.colorScheme.onBackground,
        style = MaterialTheme.typography.titleSmall,
        fontWeight = FontWeight.Black,
        modifier = Modifier.padding(top = 4.dp, bottom = 2.dp),
    )
}

@Composable
private fun LedgerExpenseCard(
    expense: Expense,
    onEdit: () -> Unit,
) {
    val visuals = LocalThemeVisuals.current
    SoftPanel(
        modifier = Modifier.clickable(onClick = onEdit),
        containerAlpha = 0.995f,
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 13.dp, vertical = 11.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            LedgerCategoryMark(category = expense.category)
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                Text(
                    text = expense.merchant?.takeIf { it.isNotBlank() } ?: "未填写商家",
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                    fontWeight = FontWeight.Black,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    text = displayTime(expense.expenseTime ?: expense.confirmedAt ?: expense.createdAt),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 1,
                )
                expense.note?.takeIf { it.isNotBlank() }?.let {
                    Text(
                        text = it,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
            Column(
                horizontalAlignment = Alignment.End,
                verticalArrangement = Arrangement.spacedBy(5.dp),
            ) {
                Text(
                    text = expense.amountCents?.let(::formatAmount) ?: "待填写",
                    color = MaterialTheme.colorScheme.primary,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Black,
                    maxLines = 1,
                )
                Text(
                    text = expense.category,
                    modifier = Modifier
                        .clip(CircleShape)
                        .background(visuals.chipSelected.copy(alpha = 0.72f))
                        .padding(horizontal = 10.dp, vertical = 5.dp),
                    color = visuals.primary,
                    style = MaterialTheme.typography.labelSmall,
                    fontWeight = FontWeight.Bold,
                    maxLines = 1,
                )
            }
        }
    }
}

@Composable
private fun LedgerCategoryMark(category: String) {
    val visuals = LocalThemeVisuals.current
    Box(
        modifier = Modifier
            .size(42.dp)
            .clip(RoundedCornerShape(15.dp))
            .background(visuals.chipSelected.copy(alpha = 0.78f)),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = category.take(1).ifBlank { "账" },
            color = visuals.primary,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Black,
            textAlign = TextAlign.Center,
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ManualExpenseSheet(
    categories: List<String>,
    saving: Boolean,
    onCreate: (ExpenseDraft) -> Unit,
    onDismiss: () -> Unit,
) {
    var amountText by rememberSaveable { mutableStateOf("") }
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

    fun draftOrMessage(): ExpenseDraft? {
        val amountCents = parseAmountCents(amountText)
        if (amountCents == null) {
            message = "请填写正确金额。"
            return null
        }
        return ExpenseDraft(
            amountCents = amountCents,
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
            .padding(horizontal = 16.dp, vertical = 10.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("手动记一笔", style = MaterialTheme.typography.titleLarge)
        Text(
            text = "适合现金、零散消费，保存后直接进入账本。",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
        OutlinedTextField(
            value = amountText,
            onValueChange = { amountText = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("金额，单位元") },
            placeholder = { Text("18.50") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            singleLine = true,
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
            LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
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
        SoftPanel(containerAlpha = 0.96f) {
            Column(
                modifier = Modifier.padding(14.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text("消费时间", style = MaterialTheme.typography.titleSmall)
                Text(displayDateTime(expenseTime), color = MaterialTheme.colorScheme.onSurfaceVariant)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { showDatePicker = true }) {
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
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(
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
private fun CategoryFilterRow(
    categories: List<String>,
    selectedCategory: String,
    onCategoryChange: (String) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(
            text = "分类",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelMedium,
        )
        LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
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
private fun SelectableFilterChip(
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

@Composable
private fun EmptyLedgerState(
    state: LedgerUiState,
    onClearFilters: () -> Unit,
    onSync: () -> Unit,
    onManualAdd: () -> Unit,
) {
    val hasMonth = state.monthFilter.isNotBlank()
    val hasCategory = state.categoryFilter.isNotBlank()
    val hasActiveFilters = hasMonth || hasCategory || state.query.isNotBlank()
    val title = when {
        hasMonth && hasCategory -> "${displayMonthLabel(state.monthFilter)} 暂无 ${state.categoryFilter} 分类账单"
        hasMonth -> "${displayMonthLabel(state.monthFilter)} 暂无已确认账单"
        hasCategory -> "暂无 ${state.categoryFilter} 分类账单"
        else -> "本地还没有已确认账单"
    }
    val body = if (hasMonth || hasCategory) {
        "可以切换月份、选择全部分类，或先同步服务器。"
    } else {
        "在待确认页确认几笔账单后，账本会在这里显示。"
    }

    AppEmptyStateCard {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            LedgerEmptyIllustration()
            Text(title, style = MaterialTheme.typography.titleMedium)
            Text(
                text = body,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(
                text = ledgerFilterSummary(state),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                if (hasActiveFilters) {
                    Button(
                        modifier = Modifier.weight(1f),
                        onClick = onClearFilters,
                    ) {
                        Text("重置筛选")
                    }
                    QuietOutlinedButton(
                        text = "同步账本",
                        modifier = Modifier.weight(1f),
                        enabled = !state.syncing,
                        onClick = onSync,
                    )
                } else {
                    Button(
                        modifier = Modifier.weight(1f),
                        onClick = onManualAdd,
                    ) {
                        Text("手动记一笔")
                    }
                    QuietOutlinedButton(
                        text = "同步账本",
                        modifier = Modifier.weight(1f),
                        enabled = !state.syncing,
                        onClick = onSync,
                    )
                }
            }
        }
    }
}

@Composable
private fun LedgerEmptyIllustration() {
    val visuals = LocalThemeVisuals.current
    Box(
        modifier = Modifier
            .size(76.dp)
            .clip(CircleShape)
            .background(visuals.primary.copy(alpha = 0.14f)),
        contentAlignment = Alignment.Center,
    ) {
        Box(
            modifier = Modifier
                .size(52.dp)
                .clip(RoundedCornerShape(18.dp))
                .background(visuals.chipSelected.copy(alpha = 0.66f)),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                imageVector = Icons.AutoMirrored.Filled.ReceiptLong,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(30.dp),
            )
        }
    }
}

private fun ledgerCombinedStatusLine(state: LedgerUiState): String {
    val syncText = when {
        state.syncing -> "同步中"
        state.lastSyncAt != null -> "同步完成 · ${ledgerSyncClock(state.lastSyncAt)}"
        else -> "离线缓存"
    }
    val month = state.monthFilter.takeIf { it.isNotBlank() }?.let(::displayMonthLabel) ?: "全部月份"
    val category = state.categoryFilter.takeIf { it.isNotBlank() } ?: "全部分类"
    val query = state.query.takeIf { it.isNotBlank() }?.let { " · 搜索“$it”" }.orEmpty()
    return "$syncText · 当前查看：$month · $category$query"
}

private fun ledgerFilterSummary(state: LedgerUiState): String {
    val month = state.monthFilter.takeIf { it.isNotBlank() }?.let(::displayMonthLabel) ?: "全部月份"
    val category = state.categoryFilter.takeIf { it.isNotBlank() } ?: "全部分类"
    val query = state.query.takeIf { it.isNotBlank() }?.let { " · 搜索“$it”" }.orEmpty()
    return "当前查看：$month · $category$query"
}

private fun ledgerStatusLine(state: LedgerUiState): String {
    return when {
        state.syncing -> "同步中"
        state.message?.contains("同步", ignoreCase = true) == true -> {
            val syncedAt = state.lastSyncAt?.let(::ledgerSyncClock)
            if (syncedAt == null) {
                "✓ ${state.message}"
            } else {
                "✓ ${state.message} · $syncedAt"
            }
        }
        state.lastSyncAt != null -> "✓ 同步完成 · ${ledgerSyncClock(state.lastSyncAt)}"
        else -> "离线可看本地缓存"
    }
}

private fun ledgerSyncClock(value: String): String {
    val label = displayTime(value)
    return label.substringAfterLast(" ").takeIf { it.isNotBlank() } ?: label
}

private data class LedgerExpenseGroup(
    val key: String,
    val label: String,
    val items: List<Expense>,
)

private fun groupLedgerExpenses(items: List<Expense>): List<LedgerExpenseGroup> {
    return items
        .groupBy { expense ->
            val date = expenseLedgerDate(expense)
            date?.toString() ?: "unknown"
        }
        .map { (key, expenses) ->
            val date = expenses.firstOrNull()?.let(::expenseLedgerDate)
            LedgerExpenseGroup(
                key = key,
                label = ledgerDayLabel(date),
                items = expenses,
            )
        }
}

private fun expenseLedgerDate(expense: Expense): LocalDate? {
    val value = expense.expenseTime ?: expense.confirmedAt ?: expense.createdAt
    return value.toLocalDateOrNull()
}

private fun String?.toLocalDateOrNull(): LocalDate? {
    if (this.isNullOrBlank()) return null
    val zone = ZoneId.systemDefault()
    return runCatching { Instant.parse(this).atZone(zone).toLocalDate() }
        .recoverCatching { OffsetDateTime.parse(this).toInstant().atZone(zone).toLocalDate() }
        .getOrNull()
}

private fun ledgerDayLabel(date: LocalDate?): String {
    if (date == null) return "未设置日期"
    val today = LocalDate.now()
    return when (date) {
        today -> "今天"
        today.minusDays(1) -> "昨天"
        else -> date.format(DateTimeFormatter.ofPattern("M月d日 E", Locale.CHINA))
    }
}
