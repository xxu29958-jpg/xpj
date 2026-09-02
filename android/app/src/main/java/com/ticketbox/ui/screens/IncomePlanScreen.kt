package com.ticketbox.ui.screens

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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Restore
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.IncomeFrequency
import com.ticketbox.domain.model.IncomePlan
import com.ticketbox.domain.model.IncomeSourceType
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppAction
import com.ticketbox.ui.components.AppContentStateCopy
import com.ticketbox.ui.components.AppContentStatePresentation
import com.ticketbox.ui.components.AppContentStateSpec
import com.ticketbox.ui.components.AppContentStateSlot
import com.ticketbox.ui.components.AppErrorState
import com.ticketbox.ui.components.AppListStateContent
import com.ticketbox.ui.components.AppListStateSpec
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppSheetActionRow
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryPageSlots
import com.ticketbox.ui.components.AppSecondaryRefreshState
import com.ticketbox.ui.components.AppSecondaryScrollableContent
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.viewmodel.IncomePlanEditUiState
import com.ticketbox.viewmodel.IncomePlanEditViewModel
import com.ticketbox.viewmodel.IncomePlanUiState
import com.ticketbox.viewmodel.IncomePlanViewModel
import com.ticketbox.viewmodel.updateDraftAmount
import com.ticketbox.viewmodel.updateDraftLabel
import com.ticketbox.viewmodel.updateDraftPayDay
import kotlinx.coroutines.delay

/** 操作成功提示的展示时长，到点自动收起，与既有 undo 卡片的定时关闭同一惯例。 */
private const val FlashDismissMillis = 4000L

private data class IncomePlanRowAction(
    val icon: ImageVector,
    val description: String,
    val onClick: () -> Unit,
)

private data class AddIncomePlanSheetActions(
    val onLabel: (String) -> Unit,
    val onSourceType: (IncomeSourceType) -> Unit,
    val onFrequency: (IncomeFrequency) -> Unit,
    val onPreviousIncomeMonth: () -> Unit,
    val onNextIncomeMonth: () -> Unit,
    val onAmount: (String) -> Unit,
    val onPayDay: (String) -> Unit,
    val onSubmit: () -> Unit,
    val onCancel: () -> Unit,
)

@Composable
fun IncomePlanScreen(
    viewModel: IncomePlanViewModel,
    editViewModel: IncomePlanEditViewModel,
    currency: CurrencyDisplay,
    onBack: () -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val editState by editViewModel.state.collectAsStateWithLifecycle()
    var showAddSheet by rememberSaveable { mutableStateOf(false) }

    IncomePlanSideEffects(
        state, editState, viewModel, editViewModel, closeAddSheet = { showAddSheet = false },
    )

    AppSecondaryScrollableContent(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Stats,
            title = stringResource(R.string.income_plan_topbar_title),
            subtitle = stringResource(R.string.income_plan_header_subtitle_compact),
            backText = stringResource(R.string.income_plan_topbar_back),
            onBack = onBack,
            hasBottomBar = false,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ),
        refresh = AppSecondaryRefreshState(
            isRefreshing = ReadableRefreshIndicator.isActive(
                loading = state.isLoading,
                hasReadableData = state.activePlans.isNotEmpty() || state.archivedPlans.isNotEmpty(),
            ),
            onRefresh = viewModel::refresh,
        ),
        slots = AppSecondaryPageSlots(
            actions = {
                if (state.canModify) {
                    AppSecondaryButton(
                        text = stringResource(R.string.income_plan_add_action_short),
                        leadingIcon = Icons.Default.Add,
                        onClick = {
                            viewModel.resetDraft()
                            showAddSheet = true
                        },
                    )
                }
            },
        ),
    ) {
        incomePlanBody(
            state = state,
            editFlash = editState.flashMessage,
            currency = currency,
            viewModel = viewModel,
            onEditPlan = editViewModel::openEdit,
        )
    }

    IncomePlanAddSheetHost(
        showAddSheet = showAddSheet,
        state = state,
        currency = currency,
        viewModel = viewModel,
        onDismiss = {
            showAddSheet = false
            viewModel.resetDraft()
        },
    )
    IncomePlanEditSheetHost(state = editState, currency = currency, editViewModel = editViewModel)
}

@Composable
private fun IncomePlanSideEffects(
    state: IncomePlanUiState,
    editState: IncomePlanEditUiState,
    viewModel: IncomePlanViewModel,
    editViewModel: IncomePlanEditViewModel,
    closeAddSheet: () -> Unit,
) {
    // 成功提示在页头横幅展示数秒后自动收起；error 由下一次 refresh 清掉，与既有语义一致。
    LaunchedEffect(state.flashMessage) {
        if (state.flashMessage == null) return@LaunchedEffect
        delay(FlashDismissMillis)
        viewModel.dismissFlash()
    }
    LaunchedEffect(editState.flashMessage) {
        if (editState.flashMessage == null) return@LaunchedEffect
        delay(FlashDismissMillis)
        editViewModel.dismissFlash()
    }
    // 成功才关抽屉：只在 create() 真正成功(addSucceeded)时收起，失败保留抽屉让 validationError 可见
    // （修「乐观关闭」——旧逻辑在 onSubmit 里按本地 addDraft.isValid 关闭、无视网络结果）。resetDraft()
    // 一并清掉一次性信号 + 草稿；effect 体全程非挂起，关闭被打断也不会把 addSucceeded 卡在 true。
    LaunchedEffect(state.addSucceeded) {
        if (!state.addSucceeded) return@LaunchedEffect
        closeAddSheet()
        viewModel.resetDraft()
    }
    // 编辑成功 ack：关编辑器 + 主列表重读。receipt 由编辑器 flashMessage 独立展示——
    // 列表 refresh 失败只出 error 横幅，不吞「已更新收入」。
    LaunchedEffect(editState.succeeded) {
        if (!editState.succeeded) return@LaunchedEffect
        editViewModel.dismiss()
        viewModel.refresh()
    }
}

private fun LazyListScope.incomePlanBody(
    state: IncomePlanUiState,
    editFlash: UiText?,
    currency: CurrencyDisplay,
    viewModel: IncomePlanViewModel,
    onEditPlan: (IncomePlan) -> Unit,
) {
    val bodyState = incomePlanBodyState(
        loadState = state.loadState,
        activeCount = state.activePlans.size,
        archivedCount = state.archivedPlans.size,
    )
    // 反馈横幅落在页头下方（/web flash 同位）：只在有消息时占位，避免空 item
    // 在 spacedBy 下留出幽灵间距。flashMessage→Success / error→Danger。
    state.flashMessage?.let { msg ->
        item { AppStatusBanner(message = msg, tone = MessageTone.Success) }
    }
    editFlash?.let { msg ->
        item { AppStatusBanner(message = msg, tone = MessageTone.Success) }
    }
    incomePlanInlineMessage(bodyState = bodyState, message = state.error)?.let { err ->
        item { AppStatusBanner(message = err, tone = MessageTone.Danger) }
    }
    if (incomePlanShowsSummary(bodyState)) {
        item {
            IncomeTotalSummary(
                expectedCents = state.currentMonthSummary.expectedAmountCents,
                planCount = state.currentMonthSummary.effectivePlanCount,
                arrivedCents = state.totalActiveAmountCents,
                currency = currency,
            )
        }
    }
    when (bodyState) {
        IncomePlanBodyState.Loading,
        IncomePlanBodyState.LoadFailed -> item {
            IncomePlanBodyStateSlot(
                bodyState = bodyState,
                error = state.error,
                onRetry = viewModel::refresh,
            )
        }
        IncomePlanBodyState.Empty,
        IncomePlanBodyState.Content -> incomePlanSections(
            state = state,
            currency = currency,
            viewModel = viewModel,
            onEditPlan = onEditPlan,
        )
    }
}

private fun LazyListScope.incomePlanSections(
    state: IncomePlanUiState,
    currency: CurrencyDisplay,
    viewModel: IncomePlanViewModel,
    onEditPlan: (IncomePlan) -> Unit,
) {
    item(key = "income-plan-active") {
        AppListStateContent(
            state = AppListStateSpec(
                isEmpty = state.activePlans.isEmpty(),
                loading = state.isLoading,
                emptyText = stringResource(R.string.income_plan_empty_body_compact),
                emptyTitle = stringResource(R.string.income_plan_empty_title),
                emptyBody = stringResource(R.string.income_plan_empty_body_compact),
            ),
        ) {
            SectionEyebrow(stringResource(R.string.income_plan_section_active))
            state.activePlans.forEach { plan ->
                IncomePlanRow(
                    plan = plan,
                    currency = currency,
                    // 行本体即编辑入口；归档收进编辑器（W2-C）。
                    onClick = if (state.canModify) ({ onEditPlan(plan) }) else null,
                )
            }
        }
    }

    if (state.archivedPlans.isNotEmpty()) {
        item { SectionEyebrow(stringResource(R.string.income_plan_section_archived)) }
        items(state.archivedPlans, key = { "archived-${it.publicId}" }) { plan ->
            IncomePlanRow(
                plan = plan,
                currency = currency,
                trailingAction = if (state.canModify) {
                    IncomePlanRowAction(
                        icon = Icons.Default.Restore,
                        description = stringResource(R.string.income_plan_card_restore_action),
                        onClick = { viewModel.restore(plan.publicId, plan.rowVersion) },
                    )
                } else {
                    null
                },
                dimmed = true,
            )
        }
    }
}

@Composable
private fun IncomePlanBodyStateSlot(
    bodyState: IncomePlanBodyState,
    error: UiText?,
    onRetry: () -> Unit,
) {
    when (bodyState) {
        IncomePlanBodyState.Loading -> AppContentStateSlot(
            state = AppContentStateSpec(
                loading = true,
                hasData = false,
                copy = AppContentStateCopy(
                    loadingTitle = stringResource(R.string.income_plan_loading_title),
                    loadingBody = stringResource(R.string.income_plan_loading_body),
                    emptyText = stringResource(R.string.income_plan_empty_body_compact),
                ),
                presentation = AppContentStatePresentation.Card,
            ),
        )
        IncomePlanBodyState.LoadFailed -> AppErrorState(
            title = error?.asString() ?: stringResource(R.string.income_plan_load_failed),
            body = stringResource(R.string.income_plan_load_failed_hint),
            onRetry = onRetry,
        )
        IncomePlanBodyState.Empty,
        IncomePlanBodyState.Content -> Unit
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

/**
 * W2-C hero 口径修正：主数字是「本月预计」（现有本月有效计划合计投影，不再冒称已到账）；
 * 服务端按计划公式的 aggregate 保留为「按计划截至今日」次要行（公式/owner 不动）。
 */
@Composable
private fun IncomeTotalSummary(
    expectedCents: Long,
    planCount: Int,
    arrivedCents: Long,
    currency: CurrencyDisplay,
) {
    Column(modifier = Modifier.fillMaxWidth()) {
        Text(
            stringResource(R.string.income_plan_expected_label),
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.size(AppSpacing.miniGap))
        Text(
            formatDisplayAmount(expectedCents, currency),
            style = MaterialTheme.typography.headlineLarge.tabularNum(),
            fontWeight = FontWeight.SemiBold,
        )
        Spacer(Modifier.size(AppSpacing.miniGap))
        Text(
            stringResource(R.string.income_plan_total_meta, planCount),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.size(AppSpacing.miniGap))
        Text(
            stringResource(
                R.string.income_plan_arrived_caption,
                formatDisplayAmount(arrivedCents, currency),
            ),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.size(AppSpacing.compactGap))
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.soft))
    }
}

@Composable
private fun IncomePlanRow(
    plan: IncomePlan,
    currency: CurrencyDisplay,
    dimmed: Boolean = false,
    onClick: (() -> Unit)? = null,
    trailingAction: IncomePlanRowAction? = null,
) {
    val rowModifier = if (onClick != null) {
        Modifier.fillMaxWidth().clickable(role = Role.Button, onClick = onClick)
    } else {
        Modifier.fillMaxWidth()
    }
    Column(modifier = rowModifier) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = AppSpacing.compactGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IncomePlanRowSummary(plan = plan, dimmed = dimmed, modifier = Modifier.weight(1f))
            Text(
                formatDisplayAmount(plan.amountCents, currency),
                style = MaterialTheme.typography.titleMedium.tabularNum(),
                fontWeight = FontWeight.SemiBold,
                color = if (dimmed) MaterialTheme.colorScheme.onSurfaceVariant
                else MaterialTheme.colorScheme.onSurface,
                textAlign = TextAlign.End,
            )
            if (trailingAction != null) {
                Spacer(Modifier.width(AppSpacing.smallGap))
                IconButton(onClick = trailingAction.onClick) {
                    Icon(trailingAction.icon, contentDescription = trailingAction.description)
                }
            } else if (onClick != null) {
                Spacer(Modifier.width(AppSpacing.smallGap))
                Icon(
                    imageVector = Icons.AutoMirrored.Filled.KeyboardArrowRight,
                    contentDescription = stringResource(R.string.income_plan_edit_action),
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.soft))
    }
}

@Composable
private fun IncomePlanRowSummary(
    plan: IncomePlan,
    dimmed: Boolean,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier) {
        Text(
            plan.label,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
            color = if (dimmed) MaterialTheme.colorScheme.onSurfaceVariant
            else MaterialTheme.colorScheme.onSurface,
        )
        Spacer(Modifier.size(AppSpacing.miniGap))
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            Text(
                stringResource(incomeSourceTypeLabelRes(plan.sourceType)),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(
                if (plan.frequency == IncomeFrequency.ONE_TIME) {
                    stringResource(
                        R.string.income_plan_card_one_time_day,
                        displayMonthLabel(plan.incomeMonth.orEmpty()),
                        plan.payDay,
                    )
                } else {
                    stringResource(R.string.income_plan_card_payday, plan.payDay)
                },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

/** 添加抽屉宿主：表单与编辑共享 [IncomePlanDraftForm]；成功才由 addSucceeded ack 关闭。 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun IncomePlanAddSheetHost(
    showAddSheet: Boolean,
    state: IncomePlanUiState,
    currency: CurrencyDisplay,
    viewModel: IncomePlanViewModel,
    onDismiss: () -> Unit,
) {
    if (!showAddSheet) return
    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
    ) {
        AddIncomePlanSheet(
            state = state,
            currency = currency,
            actions = AddIncomePlanSheetActions(
                onLabel = viewModel::updateDraftLabel,
                onSourceType = viewModel::updateDraftSource,
                onFrequency = viewModel::updateDraftFrequency,
                onPreviousIncomeMonth = { viewModel.shiftDraftIncomeMonth(-1L) },
                onNextIncomeMonth = { viewModel.shiftDraftIncomeMonth(1L) },
                onAmount = viewModel::updateDraftAmount,
                onPayDay = viewModel::updateDraftPayDay,
                onSubmit = viewModel::submitDraft,
                onCancel = onDismiss,
            ),
        )
    }
}

@Composable
private fun AddIncomePlanSheet(
    state: IncomePlanUiState,
    currency: CurrencyDisplay,
    actions: AddIncomePlanSheetActions,
) {
    AppSheetScaffold(title = stringResource(R.string.income_plan_sheet_title)) {
        IncomePlanDraftForm(
            state = IncomePlanDraftFormState(
                draft = state.addDraft,
                isSubmitting = state.isSubmitting,
            ),
            currency = currency,
            fieldCallbacks = IncomePlanDraftFieldCallbacks(
                onLabel = actions.onLabel,
                onAmount = actions.onAmount,
                onPayDay = actions.onPayDay,
                onPreviousIncomeMonth = actions.onPreviousIncomeMonth,
                onNextIncomeMonth = actions.onNextIncomeMonth,
            ),
            choiceCallbacks = IncomePlanDraftChoiceCallbacks(
                onSourceType = actions.onSourceType,
                onFrequency = actions.onFrequency,
            ),
        )
        AppSheetActionRow(
            primary = AppAction(
                text = if (state.isSubmitting) {
                    stringResource(R.string.income_plan_sheet_submitting)
                } else {
                    stringResource(R.string.income_plan_sheet_save)
                },
                onClick = actions.onSubmit,
                enabled = !state.isSubmitting,
            ),
            secondary = AppAction(
                text = stringResource(R.string.common_cancel),
                onClick = actions.onCancel,
                enabled = !state.isSubmitting,
            ),
        )
    }
}
