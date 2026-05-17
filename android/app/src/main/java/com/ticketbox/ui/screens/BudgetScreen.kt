package com.ticketbox.ui.screens

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
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
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.SafeBadge
import com.ticketbox.ui.components.SkeletonBlock
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.viewmodel.BudgetCategoryInput
import com.ticketbox.viewmodel.BudgetUiState
import com.valentinilk.shimmer.shimmer

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
    val currencyDisplay = LocalCurrencyDisplay.current

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
        item { BudgetSummaryCard(budget = state.budget, loading = state.loading, currencyDisplay = currencyDisplay) }
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
                CategoryBudgetCard(items = budget.categoryBudgets, currencyDisplay = currencyDisplay)
            }
            item {
                ExcludedBreakdownCard(items = budget.excludedBreakdown, currencyDisplay = currencyDisplay)
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
            fontWeight = AppTextHierarchy.heading.weight,
        )
        TextButton(onClick = onNextMonth) { Text("下月") }
    }
}

@Composable
private fun BudgetSummaryCard(
    budget: BudgetMonthly?,
    loading: Boolean,
    currencyDisplay: CurrencyDisplay,
) {
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
                    fontWeight = AppTextHierarchy.heading.weight,
                )
                Text(
                    text = if (budget?.configured == true) "${budget.spentPercent}%" else "未配置",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelLarge,
                )
            }
            if (budget == null) {
                if (loading) {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .shimmer(),
                        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
                    ) {
                        SkeletonBlock(modifier = Modifier.fillMaxWidth(0.8f).height(22.dp))
                        SkeletonBlock(modifier = Modifier.fillMaxWidth().height(12.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
                            SkeletonBlock(modifier = Modifier.weight(1f).height(58.dp))
                            SkeletonBlock(modifier = Modifier.weight(1f).height(58.dp))
                        }
                    }
                    return@Column
                }
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
                    value = formatDisplayAmount(budget.availableAmountCents, currencyDisplay),
                    modifier = Modifier.weight(1f),
                )
                MetricPill(
                    label = if (budget.isOverBudget) "超支" else "剩余",
                    value = formatDisplayAmount(
                        if (budget.isOverBudget) budget.overspentAmountCents else budget.remainingAmountCents,
                        currencyDisplay,
                    ),
                    modifier = Modifier.weight(1f),
                )
            }
            Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
                MetricPill(
                    label = "已花",
                    value = formatDisplayAmount(budget.spentAmountCents, currencyDisplay),
                    modifier = Modifier.weight(1f),
                )
                MetricPill(
                    label = "灵活可花",
                    value = formatDisplayAmount(budget.flexBudgetCents, currencyDisplay),
                    modifier = Modifier.weight(1f),
                )
            }
            Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
                MetricPill(
                    label = "固定支出",
                    value = formatDisplayAmount(budget.fixedAmountCents, currencyDisplay),
                    modifier = Modifier.weight(1f),
                )
                MetricPill(
                    label = "剔除",
                    value = formatDisplayAmount(budget.excludedAmountCents, currencyDisplay),
                    modifier = Modifier.weight(1f),
                )
            }
        }
    }
}

@Composable
private fun BudgetProgressBar(progress: Float) {
    val track = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.78f)
    val visuals = LocalThemeVisuals.current
    val stateTokens = com.ticketbox.ui.design.LocalStateTokens.current
    // 三档渐变：< 80% safe（primary 调色板）；80%-100% warn（黄褐）；> 100% over（红/danger）。
    // 进度条 fill 用渐变方向左→右，并让较高使用率叠一层"超线警示"色，给清晰边界感。
    val clamped = progress.coerceAtLeast(0f)
    val safeEnd = 0.80f
    val warnEnd = 1.00f
    val (start, end) = when {
        clamped <= safeEnd -> visuals.primary.copy(alpha = 0.78f) to visuals.primary.copy(alpha = 0.92f)
        clamped <= warnEnd -> stateTokens.warn.fg.copy(alpha = 0.78f) to stateTokens.warn.fg.copy(alpha = 0.95f)
        else -> stateTokens.danger.fg.copy(alpha = 0.82f) to stateTokens.danger.fg.copy(alpha = 1.0f)
    }
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(AppRadius.pill))
            .background(track),
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth(clamped.coerceAtMost(1f))
                .background(
                    androidx.compose.ui.graphics.Brush.horizontalGradient(listOf(start, end)),
                )
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
            fontWeight = AppTextHierarchy.body.weight,
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
                fontWeight = AppTextHierarchy.heading.weight,
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
                fontWeight = AppTextHierarchy.body.weight,
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
private fun CategoryBudgetCard(
    items: List<BudgetCategoryBudget>,
    currencyDisplay: CurrencyDisplay,
) {
    AppGlassCard(containerAlpha = 0.94f) {
        Column(
            modifier = Modifier.padding(AppSpacing.cardPaddingSmall),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        ) {
            Text(
                text = "分类执行",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = AppTextHierarchy.heading.weight,
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
                        detail = "已花 ${formatDisplayAmount(item.spentAmountCents, currencyDisplay)}",
                        amount = if (item.overspentAmountCents > 0L) {
                            "超 ${formatDisplayAmount(item.overspentAmountCents, currencyDisplay)}"
                        } else {
                            "剩 ${formatDisplayAmount(item.remainingAmountCents, currencyDisplay)}"
                        },
                    )
                }
            }
        }
    }
}

@Composable
private fun ExcludedBreakdownCard(
    items: List<BudgetExcludedCategory>,
    currencyDisplay: CurrencyDisplay,
) {
    AppGlassCard(containerAlpha = 0.94f) {
        Column(
            modifier = Modifier.padding(AppSpacing.cardPaddingSmall),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        ) {
            Text(
                text = "剔除明细",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = AppTextHierarchy.heading.weight,
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
                        amount = formatDisplayAmount(item.amountCents, currencyDisplay),
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
            fontWeight = AppTextHierarchy.body.weight,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}
