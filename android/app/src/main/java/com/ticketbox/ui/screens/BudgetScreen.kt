package com.ticketbox.ui.screens

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.BudgetCategoryBudget
import com.ticketbox.domain.model.BudgetExcludedCategory
import com.ticketbox.domain.model.BudgetMonthly
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.SafeBadge
import com.ticketbox.ui.components.formatAmount
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.viewmodel.BudgetCategoryInput
import com.ticketbox.viewmodel.BudgetUiState

@Composable
fun BudgetScreen(
    state: BudgetUiState,
    onRefresh: () -> Unit,
    onPreviousMonth: () -> Unit,
    onNextMonth: () -> Unit,
    onTotalAmountChange: (String) -> Unit,
    onRolloverAmountChange: (String) -> Unit,
    onNonMonthlyAmountChange: (String) -> Unit,
    onExcludedCategoriesChange: (String) -> Unit,
    onCategoryRowChange: (Int, String, String) -> Unit,
    onAddCategoryRow: () -> Unit,
    onRemoveCategoryRow: (Int) -> Unit,
    onSave: () -> Unit,
    onBack: (() -> Unit)? = null,
) {
    BackHandler(enabled = onBack != null) {
        onBack?.invoke()
    }

    AppScrollableContent(
        role = AppPageRole.Stats,
        isRefreshing = state.loading,
        onRefresh = onRefresh,
        hasBottomBar = onBack == null,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
    ) {
        item {
            Column(
                verticalArrangement = Arrangement.spacedBy(
                    if (onBack == null) AppSpacing.compactGap else AppSpacing.smallGap,
                ),
            ) {
                onBack?.let {
                    TextButton(onClick = it) {
                        Icon(
                            Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "返回统计",
                            modifier = Modifier.size(18.dp),
                        )
                        Spacer(Modifier.width(4.dp))
                        Text("返回统计")
                    }
                }
                AppPageHeader(
                    title = "预算",
                    subtitle = "${state.month} 月度可花额度",
                ) {
                    SafeBadge()
                }
                MonthSwitcher(
                    month = state.month,
                    onPreviousMonth = onPreviousMonth,
                    onNextMonth = onNextMonth,
                )
            }
        }
        state.message?.let { message ->
            item { Text(message, color = MaterialTheme.colorScheme.secondary) }
        }
        item { BudgetSummaryCard(budget = state.budget) }
        item {
            BudgetEditorCard(
                state = state,
                onTotalAmountChange = onTotalAmountChange,
                onRolloverAmountChange = onRolloverAmountChange,
                onNonMonthlyAmountChange = onNonMonthlyAmountChange,
                onExcludedCategoriesChange = onExcludedCategoriesChange,
                onCategoryRowChange = onCategoryRowChange,
                onAddCategoryRow = onAddCategoryRow,
                onRemoveCategoryRow = onRemoveCategoryRow,
                onSave = onSave,
            )
        }
        state.budget?.let { budget ->
            item {
                CategoryBudgetCard(items = budget.categoryBudgets)
            }
            item {
                ExcludedBreakdownCard(items = budget.excludedBreakdown)
            }
        }
    }
}

@Composable
private fun MonthSwitcher(
    month: String,
    onPreviousMonth: () -> Unit,
    onNextMonth: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        TextButton(onClick = onPreviousMonth) { Text("上月") }
        Text(
            text = month,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Black,
        )
        TextButton(onClick = onNextMonth) { Text("下月") }
    }
}

@Composable
private fun BudgetSummaryCard(budget: BudgetMonthly?) {
    AppGlassCard(containerAlpha = 0.94f) {
        Column(
            modifier = Modifier.padding(AppSpacing.cardPaddingSmall),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.cardPaddingTight),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = "本月预算",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Black,
                )
                Text(
                    text = if (budget?.configured == true) "${budget.spentPercent}%" else "未配置",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelLarge,
                )
            }
            if (budget == null) {
                Text(
                    text = "正在读取预算。",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodyMedium,
                )
                return@Column
            }
            BudgetProgressBar(progress = budget.spentProgress)
            Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
                MetricPill(
                    label = "总额",
                    value = formatAmount(budget.availableAmountCents),
                    modifier = Modifier.weight(1f),
                )
                MetricPill(
                    label = if (budget.isOverBudget) "超支" else "剩余",
                    value = formatAmount(if (budget.isOverBudget) budget.overspentAmountCents else budget.remainingAmountCents),
                    modifier = Modifier.weight(1f),
                )
            }
            Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
                MetricPill(
                    label = "已花",
                    value = formatAmount(budget.spentAmountCents),
                    modifier = Modifier.weight(1f),
                )
                MetricPill(
                    label = "灵活可花",
                    value = formatAmount(budget.flexBudgetCents),
                    modifier = Modifier.weight(1f),
                )
            }
            Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
                MetricPill(
                    label = "固定支出",
                    value = formatAmount(budget.fixedAmountCents),
                    modifier = Modifier.weight(1f),
                )
                MetricPill(
                    label = "剔除",
                    value = formatAmount(budget.excludedAmountCents),
                    modifier = Modifier.weight(1f),
                )
            }
        }
    }
}

@Composable
private fun BudgetProgressBar(progress: Float) {
    val track = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.78f)
    val fill = MaterialTheme.colorScheme.primary.copy(alpha = 0.88f)
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(AppRadius.pill))
            .background(track),
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth(progress.coerceIn(0f, 1f))
                .background(fill)
                .padding(vertical = AppSpacing.miniGap),
        )
    }
}

@Composable
private fun MetricPill(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
) {
    val visuals = LocalThemeVisuals.current
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(AppRadius.small))
            .background(visuals.chipUnselected.copy(alpha = 0.54f))
            .padding(horizontal = AppSpacing.compactGap, vertical = AppSpacing.contentGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        Text(
            text = label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
        )
        Text(
            text = value,
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.Bold,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun BudgetEditorCard(
    state: BudgetUiState,
    onTotalAmountChange: (String) -> Unit,
    onRolloverAmountChange: (String) -> Unit,
    onNonMonthlyAmountChange: (String) -> Unit,
    onExcludedCategoriesChange: (String) -> Unit,
    onCategoryRowChange: (Int, String, String) -> Unit,
    onAddCategoryRow: () -> Unit,
    onRemoveCategoryRow: (Int) -> Unit,
    onSave: () -> Unit,
) {
    AppGlassCard(containerAlpha = 0.94f) {
        Column(
            modifier = Modifier.padding(AppSpacing.cardPaddingSmall),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        ) {
            Text(
                text = "预算设置",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Black,
            )
            if (!state.canModify) {
                Text(
                    text = "当前角色为只读，无法修改账本。",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodyMedium,
                )
                return@Column
            }
            MoneyField(
                value = state.form.totalAmount,
                onValueChange = onTotalAmountChange,
                label = "月度总预算",
                placeholder = "3000",
            )
            Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
                MoneyField(
                    value = state.form.rolloverAmount,
                    onValueChange = onRolloverAmountChange,
                    label = "结转",
                    placeholder = "0",
                    modifier = Modifier.weight(1f),
                )
                MoneyField(
                    value = state.form.nonMonthlyAmount,
                    onValueChange = onNonMonthlyAmountChange,
                    label = "非月度预留",
                    placeholder = "0",
                    modifier = Modifier.weight(1f),
                )
            }
            OutlinedTextField(
                value = state.form.excludedCategories,
                onValueChange = onExcludedCategoriesChange,
                modifier = Modifier.fillMaxWidth(),
                label = { Text("剔除分类") },
                placeholder = { Text("医疗，报销") },
                minLines = 1,
                maxLines = 3,
            )
            Text(
                text = "分类预算",
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.Bold,
            )
            state.form.categoryRows.forEachIndexed { index, row ->
                CategoryInputRow(
                    row = row,
                    canRemove = state.form.categoryRows.size > 1,
                    onChange = { category, amount -> onCategoryRowChange(index, category, amount) },
                    onRemove = { onRemoveCategoryRow(index) },
                )
            }
            TextButton(onClick = onAddCategoryRow) {
                Icon(Icons.Filled.Add, contentDescription = "增加分类预算")
                Text("增加分类")
            }
            Button(
                modifier = Modifier.fillMaxWidth(),
                enabled = !state.saving,
                onClick = onSave,
            ) {
                Text(if (state.saving) "保存中" else "保存预算")
            }
        }
    }
}

@Composable
private fun MoneyField(
    value: String,
    onValueChange: (String) -> Unit,
    label: String,
    placeholder: String,
    modifier: Modifier = Modifier,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        modifier = modifier.fillMaxWidth(),
        label = { Text(label) },
        placeholder = { Text(placeholder) },
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
        singleLine = true,
    )
}

@Composable
private fun CategoryInputRow(
    row: BudgetCategoryInput,
    canRemove: Boolean,
    onChange: (String, String) -> Unit,
    onRemove: () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        OutlinedTextField(
            value = row.category,
            onValueChange = { onChange(it, row.amount) },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("分类") },
            placeholder = { Text("餐饮") },
            singleLine = true,
        )
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            MoneyField(
                value = row.amount,
                onValueChange = { onChange(row.category, it) },
                label = "预算金额",
                placeholder = "1000",
                modifier = Modifier.weight(1f),
            )
            IconButton(
                enabled = canRemove,
                onClick = onRemove,
            ) {
                Icon(
                    Icons.Filled.DeleteOutline,
                    contentDescription = row.category.takeIf { it.isNotBlank() }?.let { "删除 $it 分类预算" } ?: "删除分类预算",
                )
            }
        }
    }
}

@Composable
private fun CategoryBudgetCard(items: List<BudgetCategoryBudget>) {
    AppGlassCard(containerAlpha = 0.94f) {
        Column(
            modifier = Modifier.padding(AppSpacing.cardPaddingSmall),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        ) {
            Text(
                text = "分类执行",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Black,
            )
            if (items.isEmpty()) {
                Text(
                    text = "未设置分类预算。",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodyMedium,
                )
            } else {
                items.forEachIndexed { index, item ->
                    if (index > 0) HorizontalDivider()
                    AmountRow(
                        title = item.category,
                        detail = "已花 ${formatAmount(item.spentAmountCents)}",
                        amount = if (item.overspentAmountCents > 0L) {
                            "超 ${formatAmount(item.overspentAmountCents)}"
                        } else {
                            "剩 ${formatAmount(item.remainingAmountCents)}"
                        },
                    )
                }
            }
        }
    }
}

@Composable
private fun ExcludedBreakdownCard(items: List<BudgetExcludedCategory>) {
    AppGlassCard(containerAlpha = 0.94f) {
        Column(
            modifier = Modifier.padding(AppSpacing.cardPaddingSmall),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        ) {
            Text(
                text = "剔除明细",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Black,
            )
            if (items.isEmpty()) {
                Text(
                    text = "本月没有被剔除的消费。",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodyMedium,
                )
            } else {
                items.forEachIndexed { index, item ->
                    if (index > 0) HorizontalDivider()
                    AmountRow(
                        title = item.category,
                        detail = "${item.count} 笔",
                        amount = formatAmount(item.amountCents),
                    )
                }
            }
        }
    }
}

@Composable
private fun AmountRow(
    title: String,
    detail: String,
    amount: String,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(
            modifier = Modifier
                .weight(1f)
                .padding(end = 12.dp),
            verticalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            Text(
                text = title,
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = FontWeight.SemiBold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = detail,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Text(
            text = amount,
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.Bold,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}
