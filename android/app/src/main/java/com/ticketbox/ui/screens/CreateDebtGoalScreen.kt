package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.Checkbox
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppFloatingActionBar
import com.ticketbox.ui.components.AppListRow
import com.ticketbox.ui.components.AppListStateContent
import com.ticketbox.ui.components.AppListStateMessage
import com.ticketbox.ui.components.AppListStateSpec
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppButtonIcons
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryPageSlots
import com.ticketbox.ui.components.AppSecondaryRefreshState
import com.ticketbox.ui.components.AppSecondaryScrollableContent
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
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
    originalSubmissionId: Long? = null,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    LaunchedEffect(viewModel, originalSubmissionId) { viewModel.reload(originalSubmissionId) }
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
            onRefresh = viewModel::refreshCandidates,
        ),
        slots = AppSecondaryPageSlots(
            status = { CreateDebtGoalStatusStack(state, viewModel) },
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
        item { CreateDebtGoalNameField(name = state.name, enabled = state.editable, onNameChange = viewModel::updateName) }
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
private fun CreateDebtGoalStatusStack(state: CreateDebtGoalUiState, viewModel: CreateDebtGoalViewModel) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        DebtReadSource(state.fetchedAt, state.fromCache, state.isLoadingDebts)
        state.formError?.let { err -> AppStatusBanner(message = err, tone = MessageTone.Danger) }
        state.loadError?.takeIf { state.candidates.isNotEmpty() }
            ?.let { err -> AppStatusBanner(message = err, tone = MessageTone.Danger) }
        state.pending?.let { GoalCreationSubmissionStatus(it, state.isSubmitting, state.canModify, viewModel::recover) }
        DebtGoalDraftActions(state, viewModel)
        if (state.unavailableSelectedDebtIds.isNotEmpty() && state.pending == null) {
            AppStatusBanner(message = UiText.res(R.string.debt_goal_create_selection_changed), tone = MessageTone.Info)
            TextButton(enabled = state.editable, onClick = viewModel::removeUnavailableSelections) {
                Text(stringResource(R.string.debt_goal_create_remove_unavailable))
            }
        }
    }
}
@Composable
private fun CreateDebtGoalNameField(name: String, enabled: Boolean, onNameChange: (String) -> Unit) {
    DebtGoalOpenSection(
        title = stringResource(R.string.debt_goal_create_name_section),
        subtitle = stringResource(R.string.debt_goal_create_name_hint),
    ) {
        AppTextInput(
            state = AppTextInputState(
                label = stringResource(R.string.debt_goal_create_name_label),
                value = name,
                enabled = enabled,
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
        message = state.loadError?.let { AppListStateMessage(it, MessageTone.Danger) },
    ) {
        state.candidates.forEachIndexed { index, debt ->
            DebtPickerRow(
                debt = debt,
                selected = debt.publicId in state.selectedDebtIds,
                enabled = state.editable,
                onToggle = { onToggle(debt.publicId) },
                showDivider = index < state.candidates.lastIndex,
            )
        }
    }
}

@Composable
internal fun DebtPickerRow(
    debt: Debt,
    selected: Boolean,
    enabled: Boolean,
    onToggle: () -> Unit,
    showDivider: Boolean,
) {
    val name = debt.counterpartyLabel?.takeIf { it.isNotBlank() }
        ?: stringResource(debtCounterpartyFallbackRes(debt.counterpartyType))
    AppListRow(
        modifier = Modifier.fillMaxWidth(),
        onClick = { if (enabled) onToggle() },
        showDivider = showDivider,
    ) {
        Checkbox(checked = selected, enabled = enabled, onCheckedChange = { onToggle() })
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
            if (!debt.isOpen) Text(stringResource(debtLinkStatusLabelRes(debt.status)),
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
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
private fun DebtGoalDraftActions(state: CreateDebtGoalUiState, viewModel: CreateDebtGoalViewModel) {
    var discarding by remember(state.creationKey, state.originalSubmissionId) { mutableStateOf(false) }
    if (state.acceptanceUncertain || state.checkingOriginal) {
        TextButton(enabled = !state.checkingOriginal && !state.isSubmitting, onClick = viewModel::retryOriginal) {
            Text(stringResource(R.string.goal_draft_check_original))
        }
    }
    if (state.canDiscardDraft) TextButton(onClick = { discarding = true }) {
        Text(stringResource(R.string.goal_draft_discard))
    }
    if (discarding && state.canDiscardDraft) AlertDialog(
        onDismissRequest = { discarding = false },
        title = { Text(stringResource(R.string.goal_draft_discard)) },
        text = { Text(stringResource(R.string.goal_draft_discard_explanation)) },
        confirmButton = { TextButton(onClick = { discarding = false; viewModel.discardDraft() }) {
            Text(stringResource(R.string.goal_draft_discard_confirm))
        } },
        dismissButton = { TextButton(onClick = { discarding = false }) { Text(stringResource(R.string.common_cancel)) } },
    )
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
            icons = AppButtonIcons(leading = Icons.Filled.Check),
            modifier = Modifier.fillMaxWidth(),
            enabled = canSubmit,
            onClick = onSubmit,
        )
    }
}
