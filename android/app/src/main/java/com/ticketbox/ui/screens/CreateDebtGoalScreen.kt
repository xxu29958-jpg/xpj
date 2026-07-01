package com.ticketbox.ui.screens

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.AppSecondaryPageHeader
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.viewmodel.CreateDebtGoalUiState
import com.ticketbox.viewmodel.CreateDebtGoalViewModel

/**
 * ADR-0049 §6 (slice 8b) 新建还债目标：名称输入 + 未结清欠款多选选择器 →
 * [CreateDebtGoalViewModel.submit]。镜像 [DebtListScreen] 的生活流骨架
 * （[AppScrollableContent] + [AppPageHeader] + [AppGlassCard] + [AppStatusBanner]），
 * 方向 / 对象标签复用 [DebtGoalLabels]。它是 DebtGoal overlay 内的一个子页（与列表/详情
 * 互斥渲染，见 DebtGoalRoute），故自带 [BackHandler]
 * （[[project_overlay_screen_needs_own_backhandler]]）：返回回到目标列表，再返回才关 overlay。
 */
@Composable
fun CreateDebtGoalScreen(
    viewModel: CreateDebtGoalViewModel,
    currency: CurrencyDisplay,
    onBack: () -> Unit,
    onCreated: () -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    // 进入即（重新）加载候选欠款 + 重置草稿（账本隔离 + 拉到刚记的新欠款）。
    LaunchedEffect(Unit) { viewModel.reload() }
    // 创建成功的一次性信号：关闭新建页 + 让目标列表重拉，然后消费信号。
    LaunchedEffect(state.createdPublicId) {
        if (state.createdPublicId != null) {
            onCreated()
            viewModel.consumeCreated()
        }
    }
    BackHandler(onBack = onBack)

    AppScrollableContent(
        role = AppPageRole.Stats,
        isRefreshing = ReadableRefreshIndicator.isActive(
            loading = state.isLoadingDebts,
            hasReadableData = state.candidates.isNotEmpty(),
        ),
        onRefresh = viewModel::reload,
        hasBottomBar = false,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
    ) {
        item { CreateDebtGoalHeader(onBack = onBack) }
        item { CreateDebtGoalNameField(name = state.name, onNameChange = viewModel::updateName) }
        state.formError?.let { err -> item { AppStatusBanner(message = err, tone = MessageTone.Danger) } }
        state.loadError?.let { err -> item { AppStatusBanner(message = err, tone = MessageTone.Danger) } }
        item { PickerSectionEyebrow(stringResource(R.string.debt_goal_create_picker_title)) }
        debtPickerSection(state = state, currency = currency, onToggle = viewModel::toggleDebt)
        item {
            CreateDebtGoalFooter(
                selectedCount = state.selectedDebtIds.size,
                canSubmit = state.canSubmit && state.canModify,
                isSubmitting = state.isSubmitting,
                onSubmit = viewModel::submit,
            )
        }
    }
}

@Composable
private fun CreateDebtGoalHeader(onBack: () -> Unit) {
    AppSecondaryPageHeader(
        title = stringResource(R.string.debt_goal_create_title),
        subtitle = stringResource(R.string.debt_goal_create_intro),
        backText = stringResource(R.string.debt_goal_create_back),
        onBack = onBack,
    )
}

@Composable
private fun CreateDebtGoalNameField(name: String, onNameChange: (String) -> Unit) {
    AppGlassCard(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.fillMaxWidth().padding(AppSpacing.cardPadding)) {
            OutlinedTextField(
                value = name,
                onValueChange = onNameChange,
                label = { Text(stringResource(R.string.debt_goal_create_name_label)) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
        }
    }
}

private fun LazyListScope.debtPickerSection(
    state: CreateDebtGoalUiState,
    currency: CurrencyDisplay,
    onToggle: (String) -> Unit,
) {
    if (state.candidates.isEmpty() && !state.isLoadingDebts) {
        item { CreateDebtGoalPickerEmpty() }
        return
    }
    items(state.candidates, key = { it.publicId }) { debt ->
        DebtPickerRow(
            debt = debt,
            selected = debt.publicId in state.selectedDebtIds,
            currency = currency,
            onToggle = { onToggle(debt.publicId) },
        )
    }
}

@Composable
private fun DebtPickerRow(
    debt: Debt,
    selected: Boolean,
    currency: CurrencyDisplay,
    onToggle: () -> Unit,
) {
    val name = debt.counterpartyLabel?.takeIf { it.isNotBlank() }
        ?: stringResource(debtCounterpartyFallbackRes(debt.counterpartyType))
    AppGlassCard(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.fillMaxWidth().clickable(onClick = onToggle).padding(AppSpacing.cardPadding),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Checkbox(checked = selected, onCheckedChange = { onToggle() })
            Spacer(Modifier.width(AppSpacing.smallGap))
            Column(modifier = Modifier.weight(1f)) {
                Text(name, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.size(AppSpacing.miniGap))
                DebtStatusBadge(
                    text = stringResource(debtDirectionLabelRes(debt.direction)),
                    tone = LocalStateTokens.current.neutral,
                )
            }
            Spacer(Modifier.width(AppSpacing.smallGap))
            Text(
                formatDisplayAmount(debt.remainingAmountCents, currency),
                style = MaterialTheme.typography.titleMedium.tabularNum(),
                fontWeight = FontWeight.SemiBold,
            )
        }
    }
}

@Composable
private fun CreateDebtGoalPickerEmpty() {
    AppGlassCard(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(AppSpacing.sectionGap),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                stringResource(R.string.debt_goal_create_picker_empty_title),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
            Spacer(Modifier.size(AppSpacing.smallGap))
            Text(
                stringResource(R.string.debt_goal_create_picker_empty_body),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun CreateDebtGoalFooter(
    selectedCount: Int,
    canSubmit: Boolean,
    isSubmitting: Boolean,
    onSubmit: () -> Unit,
) {
    Column(modifier = Modifier.fillMaxWidth(), horizontalAlignment = Alignment.End) {
        Text(
            stringResource(R.string.debt_goal_create_selected_count, selectedCount),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.size(AppSpacing.smallGap))
        Button(onClick = onSubmit, enabled = canSubmit) {
            Text(
                if (isSubmitting) {
                    stringResource(R.string.debt_goal_create_submitting)
                } else {
                    stringResource(R.string.debt_goal_create_save)
                },
            )
        }
    }
}

@Composable
private fun PickerSectionEyebrow(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.labelMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(top = AppSpacing.smallGap),
    )
}
