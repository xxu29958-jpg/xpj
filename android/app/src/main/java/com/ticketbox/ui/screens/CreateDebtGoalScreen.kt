package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.components.AppDataAuthorityStrip
import com.ticketbox.ui.components.AppFloatingActionBar
import com.ticketbox.ui.components.AppListRow
import com.ticketbox.ui.components.AppListStateContent
import com.ticketbox.ui.components.AppListStateSpec
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryPageSlots
import com.ticketbox.ui.components.AppSecondaryRefreshState
import com.ticketbox.ui.components.AppSecondaryScrollableContent
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.components.DataAuthorityTone
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.viewmodel.CreateDebtGoalUiState
import com.ticketbox.viewmodel.CreateDebtGoalViewModel

/**
 * ADR-0049 §6 (slice 8b) 新建还债目标：名称输入 + 未结清欠款多选选择器 →
 * [CreateDebtGoalViewModel.submit]。镜像 [DebtListScreen] 的生活流骨架
 * （[AppScrollableContent] + [AppSecondaryPageHeader] + [AppStatusBanner]），
 * 方向 / 对象标签复用 [DebtGoalLabels]。它是 DebtGoal overlay 内的一个子页（与列表/详情
 * 互斥渲染，见 DebtGoalRoute），故自带 [BackHandler]
 * （[[project_overlay_screen_needs_own_backhandler]]）：返回回到目标列表，再返回才关 overlay。
 */
@Composable
fun CreateDebtGoalScreen(
    viewModel: CreateDebtGoalViewModel,
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
    AppSecondaryScrollableContent(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Stats,
            title = stringResource(R.string.debt_goal_create_title),
            subtitle = stringResource(R.string.debt_goal_create_intro),
            backText = stringResource(R.string.debt_goal_create_back),
            onBack = onBack,
            hasBottomBar = false,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.sectionGap),
        ),
        refresh = AppSecondaryRefreshState(
            isRefreshing = ReadableRefreshIndicator.isActive(
                loading = state.isLoadingDebts,
                hasReadableData = state.candidates.isNotEmpty(),
            ),
            onRefresh = viewModel::reload,
        ),
        slots = AppSecondaryPageSlots(
            status = { CreateDebtGoalStatusStack(state = state) },
            bottomBar = {
                CreateDebtGoalFooter(
                    selectedCount = state.selectedDebtIds.size,
                    canSubmit = state.canSubmit && state.canModify,
                    isSubmitting = state.isSubmitting,
                    onSubmit = viewModel::submit,
                )
            },
        ),
    ) {
        item { CreateDebtGoalNameField(name = state.name, onNameChange = viewModel::updateName) }
        item {
            DebtGoalOpenSection(
                title = stringResource(R.string.debt_goal_create_picker_title),
                subtitle = stringResource(R.string.debt_goal_create_picker_subtitle),
            ) {
                DebtGoalPickerContent(
                    state = state,
                    onToggle = viewModel::toggleDebt,
                )
            }
        }
    }
}

@Composable
private fun CreateDebtGoalStatusStack(state: CreateDebtGoalUiState) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        AppDataAuthorityStrip(
            tone = if (state.isLoadingDebts) DataAuthorityTone.Refreshing else DataAuthorityTone.Backend,
        )
        state.formError?.let { err -> AppStatusBanner(message = err, tone = MessageTone.Danger) }
        state.loadError?.let { err -> AppStatusBanner(message = err, tone = MessageTone.Danger) }
    }
}
@Composable
private fun CreateDebtGoalNameField(name: String, onNameChange: (String) -> Unit) {
    DebtGoalOpenSection(
        title = stringResource(R.string.debt_goal_create_name_section),
        subtitle = stringResource(R.string.debt_goal_create_name_hint),
    ) {
        AppTextInput(
            state = AppTextInputState(
                label = stringResource(R.string.debt_goal_create_name_label),
                value = name,
            ),
            actions = AppTextInputActions(onValueChange = onNameChange),
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

@Composable
private fun DebtGoalPickerContent(
    state: CreateDebtGoalUiState,
    onToggle: (String) -> Unit,
) {
    AppListStateContent(
        state = AppListStateSpec(
            isEmpty = state.candidates.isEmpty(),
            loading = state.isLoadingDebts,
            emptyText = stringResource(R.string.debt_goal_create_picker_empty_body),
            emptyTitle = stringResource(R.string.debt_goal_create_picker_empty_title),
            emptyBody = stringResource(R.string.debt_goal_create_picker_empty_body),
        ),
    ) {
        state.candidates.forEachIndexed { index, debt ->
            DebtPickerRow(
                debt = debt,
                selected = debt.publicId in state.selectedDebtIds,
                onToggle = { onToggle(debt.publicId) },
                showDivider = index < state.candidates.lastIndex,
            )
        }
    }
}

@Composable
private fun DebtPickerRow(
    debt: Debt,
    selected: Boolean,
    onToggle: () -> Unit,
    showDivider: Boolean,
) {
    val name = debt.counterpartyLabel?.takeIf { it.isNotBlank() }
        ?: stringResource(debtCounterpartyFallbackRes(debt.counterpartyType))
    AppListRow(
        modifier = Modifier.fillMaxWidth(),
        onClick = onToggle,
        showDivider = showDivider,
    ) {
        Checkbox(checked = selected, onCheckedChange = { onToggle() })
        Spacer(Modifier.width(AppSpacing.smallGap))
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            Text(name, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
            DebtStatusBadge(
                text = stringResource(debtDirectionLabelRes(debt.direction)),
                tone = LocalStateTokens.current.neutral,
            )
            Text(
                stringResource(
                    R.string.debt_goal_create_remaining_amount,
                    // R14-3：record 口径（每笔欠款自带 homeCurrencyCode，未知码原样亮码），
                    // 不用恒 Base 的环境 display。
                    formatDisplayAmount(debt.remainingAmountCents, CurrencyDisplay.forRecord(debt.homeCurrencyCode)),
                ),
                style = MaterialTheme.typography.bodySmall.tabularNum(),
                fontWeight = FontWeight.SemiBold,
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
    AppFloatingActionBar {
        Text(
            stringResource(R.string.debt_goal_create_selected_count, selectedCount),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        AppPrimaryButton(
            text = if (isSubmitting) {
                stringResource(R.string.debt_goal_create_submitting)
            } else {
                stringResource(R.string.debt_goal_create_save)
            },
            icon = Icons.Filled.Check,
            modifier = Modifier.fillMaxWidth(),
            enabled = canSubmit,
            onClick = onSubmit,
        )
    }
}
