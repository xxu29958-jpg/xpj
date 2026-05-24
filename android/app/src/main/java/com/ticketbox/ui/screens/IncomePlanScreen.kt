package com.ticketbox.ui.screens

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material.icons.filled.Restore
import androidx.compose.material3.Button
import androidx.compose.material3.CenterAlignedTopAppBar
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.IncomePlan
import com.ticketbox.domain.model.IncomeSourceType
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.IncomePlanUiState
import com.ticketbox.viewmodel.IncomePlanViewModel
import kotlinx.coroutines.launch

/**
 * v1.1 收入计划 — Android 生活流：KPI 卡 → 卡片列 → FAB → 底部抽屉添加。
 *
 * 不照搬 /web 的"表 + form"，按移动端单手操作模式：每条收入是一个卡片，
 * 主操作在卡片本身，添加进底部抽屉。共享 design token 通过
 * MaterialTheme + AppSpacing + AppGlassCard（参考 [[feedback_three_surface_visual_sync]]：
 * token 同步是硬约束；layout 按端特点自决）。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun IncomePlanScreen(
    viewModel: IncomePlanViewModel,
    currency: CurrencyDisplay,
    onBack: () -> Unit,
) {
    val state by viewModel.state.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }
    val coroutineScope = rememberCoroutineScope()
    var showAddSheet by rememberSaveable { mutableStateOf(false) }
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)

    LaunchedEffect(state.flashMessage) {
        val msg = state.flashMessage ?: return@LaunchedEffect
        snackbarHostState.showSnackbar(msg)
        viewModel.dismissFlash()
    }
    LaunchedEffect(state.error) {
        val err = state.error ?: return@LaunchedEffect
        snackbarHostState.showSnackbar(err)
    }

    BackHandler(onBack = onBack)

    Scaffold(
        topBar = {
            CenterAlignedTopAppBar(
                title = { Text("收入计划") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        },
        snackbarHost = { SnackbarHost(snackbarHostState) },
        floatingActionButton = {
            if (state.canModify) {
                ExtendedFloatingActionButton(
                    onClick = {
                        viewModel.resetDraft()
                        showAddSheet = true
                    },
                    icon = { Icon(Icons.Default.Add, contentDescription = null) },
                    text = { Text("添加收入") },
                )
            }
        },
        containerColor = MaterialTheme.colorScheme.surface,
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(
                    top = AppSpacing.compactGap + padding.calculateTopPadding(),
                    bottom = AppSpacing.sectionGap + padding.calculateBottomPadding(),
                    start = AppSpacing.cardPadding,
                    end = AppSpacing.cardPadding,
                ),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            Text(
                "声明每月收入，用于算「本月可自由支配」。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            IncomeTotalCard(totalCents = state.totalActiveAmountCents, currency = currency)

            if (state.activePlans.isEmpty() && !state.isLoading) {
                EmptyStateCard()
            } else {
                SectionEyebrow("在用")
                state.activePlans.forEach { plan ->
                    IncomePlanCard(
                        plan = plan,
                        currency = currency,
                        canModify = state.canModify,
                        trailingIcon = Icons.Default.DeleteOutline,
                        trailingDescription = "归档",
                        onTrailing = { viewModel.archive(plan.publicId) },
                    )
                }
            }

            if (state.archivedPlans.isNotEmpty()) {
                SectionEyebrow("已归档")
                state.archivedPlans.forEach { plan ->
                    IncomePlanCard(
                        plan = plan,
                        currency = currency,
                        canModify = state.canModify,
                        trailingIcon = Icons.Default.Restore,
                        trailingDescription = "恢复",
                        onTrailing = { viewModel.restore(plan.publicId) },
                        dimmed = true,
                    )
                }
            }
        }
    }

    if (showAddSheet) {
        ModalBottomSheet(
            onDismissRequest = {
                showAddSheet = false
                viewModel.resetDraft()
            },
            sheetState = sheetState,
        ) {
            AddIncomePlanSheet(
                state = state,
                onLabel = viewModel::updateDraftLabel,
                onSourceType = viewModel::updateDraftSource,
                onAmount = viewModel::updateDraftAmount,
                onPayDay = viewModel::updateDraftPayDay,
                onSubmit = {
                    viewModel.submitDraft()
                    coroutineScope.launch {
                        if (state.addDraft.isValid) {
                            sheetState.hide()
                            showAddSheet = false
                        }
                    }
                },
                onCancel = {
                    showAddSheet = false
                    viewModel.resetDraft()
                },
            )
        }
    }
}

@Composable
private fun SectionEyebrow(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.labelMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(top = AppSpacing.smallGap),
    )
}

@Composable
private fun IncomeTotalCard(totalCents: Long, currency: CurrencyDisplay) {
    AppGlassCard(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(AppSpacing.cardPadding)) {
            Text(
                "月度收入总额",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.size(AppSpacing.miniGap))
            Text(
                formatDisplayAmount(totalCents, currency),
                style = MaterialTheme.typography.displaySmall,
                fontWeight = FontWeight.SemiBold,
            )
            Spacer(Modifier.size(AppSpacing.miniGap))
            Text(
                "来自下方所有 “在用” 状态的收入计划。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun IncomePlanCard(
    plan: IncomePlan,
    currency: CurrencyDisplay,
    canModify: Boolean,
    trailingIcon: ImageVector,
    trailingDescription: String,
    onTrailing: () -> Unit,
    dimmed: Boolean = false,
) {
    AppGlassCard(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(AppSpacing.cardPadding),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    plan.label,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = if (dimmed) MaterialTheme.colorScheme.onSurfaceVariant
                    else MaterialTheme.colorScheme.onSurface,
                )
                Spacer(Modifier.size(AppSpacing.miniGap))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        plan.sourceType.displayName,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.width(AppSpacing.smallGap))
                    Box(
                        modifier = Modifier
                            .size(width = 1.dp, height = 12.dp)
                            .background(MaterialTheme.colorScheme.outlineVariant),
                    )
                    Spacer(Modifier.width(AppSpacing.smallGap))
                    Text(
                        "每月 ${plan.payDay} 号",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            Text(
                formatDisplayAmount(plan.amountCents, currency),
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.SemiBold,
                color = if (dimmed) MaterialTheme.colorScheme.onSurfaceVariant
                else MaterialTheme.colorScheme.onSurface,
            )
            if (canModify) {
                Spacer(Modifier.width(AppSpacing.smallGap))
                IconButton(onClick = onTrailing) {
                    Icon(trailingIcon, contentDescription = trailingDescription)
                }
            }
        }
    }
}

@Composable
private fun EmptyStateCard() {
    AppGlassCard(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(AppSpacing.sectionGap),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                "还没有收入计划",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
            Spacer(Modifier.size(AppSpacing.smallGap))
            Text(
                "点右下角 “添加收入”，写好后「本月可自由支配」才能算出来。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun AddIncomePlanSheet(
    state: IncomePlanUiState,
    onLabel: (String) -> Unit,
    onSourceType: (IncomeSourceType) -> Unit,
    onAmount: (String) -> Unit,
    onPayDay: (String) -> Unit,
    onSubmit: () -> Unit,
    onCancel: () -> Unit,
) {
    val draft = state.addDraft
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(AppSpacing.cardPadding),
    ) {
        Text(
            "添加收入",
            style = MaterialTheme.typography.titleLarge,
            fontWeight = FontWeight.SemiBold,
        )
        Spacer(Modifier.size(AppSpacing.cardPadding))

        OutlinedTextField(
            value = draft.label,
            onValueChange = onLabel,
            label = { Text("名称") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.size(AppSpacing.compactGap))

        Text(
            "类型",
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.size(AppSpacing.miniGap))
        Row(modifier = Modifier.fillMaxWidth()) {
            IncomeSourceType.entries.forEach { source ->
                FilterChip(
                    selected = draft.sourceType == source,
                    onClick = { onSourceType(source) },
                    label = { Text(source.displayName) },
                    modifier = Modifier.padding(end = AppSpacing.miniGap),
                )
            }
        }
        Spacer(Modifier.size(AppSpacing.compactGap))

        OutlinedTextField(
            value = draft.amountYuanInput,
            onValueChange = onAmount,
            label = { Text("金额（元 / 月）") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.size(AppSpacing.compactGap))

        OutlinedTextField(
            value = draft.payDayInput,
            onValueChange = onPayDay,
            label = { Text("发薪日 (1-31)") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            modifier = Modifier.fillMaxWidth(),
        )

        if (draft.validationError != null) {
            Spacer(Modifier.size(AppSpacing.smallGap))
            Text(
                draft.validationError,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
            )
        }

        Spacer(Modifier.size(AppSpacing.cardPadding))
        HorizontalDivider()
        Spacer(Modifier.size(AppSpacing.compactGap))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.End,
        ) {
            TextButton(onClick = onCancel) { Text("取消") }
            Spacer(Modifier.width(AppSpacing.smallGap))
            Button(
                onClick = onSubmit,
                enabled = !state.isSubmitting,
            ) {
                Text(if (state.isSubmitting) "提交中…" else "保存")
            }
        }
        Spacer(Modifier.size(AppSpacing.compactGap))
    }
}
