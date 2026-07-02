package com.ticketbox.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.DebtGoalComposition
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.components.AppDataAuthorityStrip
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryPageSlots
import com.ticketbox.ui.components.AppSecondaryRefreshState
import com.ticketbox.ui.components.AppSecondaryScrollableContent
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.DataAuthorityTone
import com.ticketbox.ui.components.PrimaryCtaButton
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.viewmodel.DebtGoalUiState
import com.ticketbox.viewmodel.DebtGoalViewModel
import kotlinx.coroutines.delay

/** 操作成功提示展示时长，到点自动收起（与 IncomePlanScreen 同惯例）。 */
private const val DebtGoalFlashDismissMillis = 4000L

/**
 * ADR-0049 §6 (slice 7) 还债目标：列表 → 详情（同一 overlay 内）。详情展示评估状态 +
 * 关联欠款（未结清 / 已结清 / 已作废），并在 needs_review 时给出 §6/F13 复核两出口
 * （移除作废欠款 / 保留存档）。本切片只读 + 复核，创建还债目标随后续债务管理界面落地。
 *
 * 复用共享骨架（[AppScrollableContent] + secondary header +
 * [AppStatusBanner]），三端 token 同步走 MaterialTheme + AppSpacing。屏接 VM（与
 * IncomePlanScreen 同形），返回先收详情、再关 overlay（overlay 无 NavHost 回退栈，
 * 必须自带 [BackHandler] — [[project_overlay_screen_needs_own_backhandler]]）。
 */
@Composable
fun DebtGoalScreen(
    viewModel: DebtGoalViewModel,
    currency: CurrencyDisplay,
    onBack: () -> Unit,
    onCreate: () -> Unit,
    onOpenLinkedDebt: (String) -> Unit = {},
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val handleBack = {
        if (state.selectedGoal != null) viewModel.closeDetail() else onBack()
    }

    LaunchedEffect(state.flashMessage) {
        if (state.flashMessage == null) return@LaunchedEffect
        delay(DebtGoalFlashDismissMillis)
        viewModel.dismissFlash()
    }

    val selected = state.selectedGoal
    // 8e-6a「先清小的」排序 + 8e-6c 还清日期 picker 显隐：详情层 composable-local 视图态（无持久化/无 DataStore；
    // 排序刻意不 keyed-by-goal=会话级视图偏好，跨 closeDetail 保留）。picker 对话框在 AppScrollableContent **外**渲染。
    var sortMode by rememberSaveable { mutableStateOf(DebtPlanSortMode.Default) }
    var showDatePicker by rememberSaveable { mutableStateOf(false) }
    val callbacks = DebtGoalScreenBodyCallbacks(
        handleBack = handleBack,
        onCreate = onCreate,
        onOpenLinkedDebt = onOpenLinkedDebt,
        detailCallbacks = DebtGoalDetailCallbacks(
            sortMode = sortMode,
            onSortModeChange = { sortMode = it },
            onSetTargetDate = { showDatePicker = true },
        ),
    )
    DebtGoalScreenBody(state = state, currency = currency, viewModel = viewModel, callbacks = callbacks)
    DebtTargetDatePickerDialog(
        visible = showDatePicker,
        selected = selected,
        onSetTargetDate = viewModel::setTargetDate,
        onDismiss = { showDatePicker = false },
    )
}

private data class DebtGoalScreenBodyCallbacks(
    val handleBack: () -> Unit,
    val onCreate: () -> Unit,
    val onOpenLinkedDebt: (String) -> Unit,
    val detailCallbacks: DebtGoalDetailCallbacks,
)

@Composable
private fun DebtGoalScreenBody(
    state: DebtGoalUiState,
    currency: CurrencyDisplay,
    viewModel: DebtGoalViewModel,
    callbacks: DebtGoalScreenBodyCallbacks,
) {
    val selected = state.selectedGoal
    val createAction: (@Composable () -> Unit)? =
        if (selected == null && state.canModify) {
            {
                PrimaryCtaButton(
                    text = stringResource(R.string.debt_goal_create_cta),
                    icon = Icons.Default.Add,
                    onClick = callbacks.onCreate,
                )
            }
        } else {
            null
        }

    AppSecondaryScrollableContent(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Stats,
            title = selected?.name ?: stringResource(R.string.debt_goal_topbar_title),
            subtitle = if (selected == null) stringResource(R.string.debt_goal_intro_body) else null,
            backText = stringResource(R.string.debt_goal_topbar_back),
            onBack = callbacks.handleBack,
            hasBottomBar = false,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.sectionGap),
        ),
        refresh = AppSecondaryRefreshState(
            isRefreshing = ReadableRefreshIndicator.isActive(
                loading = state.isLoading,
                hasReadableData = selected != null || state.goals.isNotEmpty(),
            ),
            onRefresh = { viewModel.refresh() },
        ),
        slots = AppSecondaryPageSlots(
            status = { DebtGoalStatusStack(state = state) },
            actions = createAction,
        ),
    ) {
        if (selected != null) {
            debtGoalDetailSection(
                state = state,
                currency = currency,
                viewModel = viewModel,
                onOpenLinkedDebt = callbacks.onOpenLinkedDebt,
                callbacks = callbacks.detailCallbacks,
            )
        } else {
            debtGoalListSection(state = state, viewModel = viewModel)
        }
    }
}

@Composable
private fun DebtGoalStatusStack(state: DebtGoalUiState) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        AppDataAuthorityStrip(
            tone = if (state.isLoading) DataAuthorityTone.Refreshing else DataAuthorityTone.Backend,
        )
        state.flashMessage?.let { msg ->
            AppStatusBanner(message = msg, tone = MessageTone.Success)
        }
        state.error?.let { err ->
            AppStatusBanner(message = err, tone = MessageTone.Danger)
        }
    }
}
private fun LazyListScope.debtGoalListSection(
    state: DebtGoalUiState,
    viewModel: DebtGoalViewModel,
) {
    val summary = debtGoalListSummary(goals = state.goals, isLoading = state.isLoading)
    item { DebtGoalOverviewSection(summary = summary) }
    item {
        DebtGoalOpenSection(
            title = stringResource(R.string.debt_goal_list_title),
            subtitle = stringResource(R.string.debt_goal_list_subtitle),
        ) {
            if (summary.loadingWithoutData) {
                Text(
                    stringResource(R.string.debt_goal_list_loading),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
    if (state.goals.isEmpty() && !state.isLoading) {
        item { DebtGoalEmptyState() }
        return
    }
    items(state.goals, key = { it.publicId }) { goal ->
        DebtGoalListRow(goal = goal, onClick = { viewModel.openDetail(goal) })
        DebtGoalRowDivider()
    }
}

@Composable
private fun DebtGoalOverviewSection(summary: DebtGoalListSummary) {
    DebtGoalOpenSection(
        title = stringResource(R.string.debt_goal_overview_title),
        subtitle = stringResource(R.string.debt_goal_overview_subtitle),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        DebtGoalMetricRow(
            label = stringResource(R.string.debt_goal_metric_active),
            value = stringResource(R.string.debt_goal_metric_goal_count, summary.activeGoalCount),
        )
        DebtGoalRowDivider()
        DebtGoalMetricRow(
            label = stringResource(R.string.debt_goal_metric_achieved),
            value = stringResource(R.string.debt_goal_metric_goal_count, summary.achievedGoalCount),
        )
        DebtGoalRowDivider()
        DebtGoalMetricRow(
            label = stringResource(R.string.debt_goal_metric_review),
            value = stringResource(R.string.debt_goal_metric_goal_count, summary.reviewGoalCount),
        )
        DebtGoalRowDivider()
        DebtGoalMetricRow(
            label = stringResource(R.string.debt_goal_metric_linked_debts),
            value = stringResource(R.string.debt_goal_metric_debt_count, summary.linkedDebtCount),
        )
        DebtGoalRowDivider()
        DebtGoalMetricRow(
            label = stringResource(R.string.debt_goal_metric_open_debts),
            value = stringResource(R.string.debt_goal_metric_debt_count, summary.openDebtCount),
        )
    }
}

@Composable
private fun DebtGoalMetricRow(label: String, value: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            text = value,
            style = MaterialTheme.typography.titleMedium.tabularNum(),
            fontWeight = FontWeight.SemiBold,
            color = MaterialTheme.colorScheme.onSurface,
        )
    }
}

@Composable
private fun DebtGoalListRow(goal: Goal, onClick: () -> Unit) {
    val evaluation = goal.debtRepayment
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(vertical = AppSpacing.compactGap),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
            Text(
                goal.name,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                stringResource(
                    R.string.debt_goal_row_meta,
                    evaluation?.clearedCount ?: 0,
                    evaluation?.totalCount ?: 0,
                    evaluation?.remainingCount ?: 0,
                ),
                style = MaterialTheme.typography.bodySmall.tabularNum(),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Column(horizontalAlignment = Alignment.End, verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
            if (evaluation != null) {
                DebtStatusBadge(
                    text = stringResource(debtGoalEvaluationLabelRes(evaluation.evaluationState)),
                    tone = debtGoalEvaluationTone(evaluation.evaluationState),
                )
            }
            if (evaluation?.needsReview == true) {
                Text(
                    stringResource(R.string.debt_goal_card_needs_review),
                    style = MaterialTheme.typography.labelSmall,
                    color = LocalStateTokens.current.warn.fg,
                )
            }
        }
    }
}

@Composable
private fun DebtGoalEmptyState() {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        horizontalAlignment = Alignment.Start,
    ) {
        Text(
            stringResource(R.string.debt_goal_empty_title),
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
        )
        Text(
            stringResource(R.string.debt_goal_empty_body),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

private fun LazyListScope.debtGoalDetailSection(
    state: DebtGoalUiState,
    currency: CurrencyDisplay,
    viewModel: DebtGoalViewModel,
    onOpenLinkedDebt: (String) -> Unit,
    callbacks: DebtGoalDetailCallbacks,
) {
    val goal = state.selectedGoal ?: return
    val evaluation = goal.debtRepayment ?: return
    // §6 hero：件数为主视觉的关系进度卡（含状态徽章 + 达成态 + 8e-6c 纯外部债三态/还清日期/设日期入口）。
    item {
        DebtPlanProgressCard(
            evaluation = evaluation,
            currency = currency,
            canModify = state.canModify,
            onSetTargetDate = callbacks.onSetTargetDate,
        )
    }
    if (evaluation.needsReview) {
        item {
            DebtGoalIntegrityReviewCard(
                achieved = evaluation.isAchieved,
                canRemoveVoided = evaluation.nonVoidedDebtPublicIds.isNotEmpty(),
                canModify = state.canModify,
                isSubmitting = state.isSubmitting,
                onAction = { action ->
                    when (action) {
                        DebtIntegrityAction.Acknowledge -> viewModel.acknowledge()
                        DebtIntegrityAction.RemoveVoided -> viewModel.removeVoidedDebts()
                        DebtIntegrityAction.Archive -> viewModel.archiveSelected()
                    }
                },
            )
        }
    }
    // 8e-6a：「先清小的」排序只对**纯外部债**开放（§7.0 红线，成员/混装不做清偿排序器）。
    // 必须用 `== External`（`!= Member` 会误纳 Mixed）。排序对**冻结快照**纯客户端算术、返回新列表，
    // `items(key = debtPublicId)` 因稳定 key 平滑重组（不改源 list，对抗审 C2）。
    val isPureExternal = evaluation.composition == DebtGoalComposition.External
    item {
        DebtGoalOpenSection(
            title = stringResource(R.string.debt_goal_detail_links_title),
            subtitle = stringResource(R.string.debt_goal_detail_links_subtitle),
        ) {
            if (isPureExternal) {
                DebtPlanSortToggle(mode = callbacks.sortMode, onModeChange = callbacks.onSortModeChange)
            }
        }
    }
    val links =
        if (isPureExternal) evaluation.linkedDebts.sortedForPlan(callbacks.sortMode) else evaluation.linkedDebts
    items(links, key = { it.debtPublicId }) { link ->
        DebtGoalLinkRow(link = link, currency = currency, onClick = onOpenLinkedDebt)
    }
}

/** The §6/F13 integrity-review exits the UI can offer (mapped to VM actions). */
internal enum class DebtIntegrityAction { Acknowledge, RemoveVoided, Archive }

@Composable
private fun DebtGoalIntegrityReviewCard(
    achieved: Boolean,
    canRemoveVoided: Boolean,
    canModify: Boolean,
    isSubmitting: Boolean,
    onAction: (DebtIntegrityAction) -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        Text(
            stringResource(R.string.debt_goal_review_title),
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.SemiBold,
            color = LocalStateTokens.current.warn.fg,
        )
        Text(
            stringResource(
                when {
                    achieved -> R.string.debt_goal_review_body_achieved
                    canRemoveVoided -> R.string.debt_goal_review_body_not_evaluable
                    else -> R.string.debt_goal_review_body_all_voided
                },
            ),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        if (canModify) {
            DebtGoalIntegrityActions(
                achieved = achieved,
                canRemoveVoided = canRemoveVoided,
                isSubmitting = isSubmitting,
                onAction = onAction,
            )
        }
    }
}

@Composable
private fun DebtGoalIntegrityActions(
    achieved: Boolean,
    canRemoveVoided: Boolean,
    isSubmitting: Boolean,
    onAction: (DebtIntegrityAction) -> Unit,
) {
    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
        when {
            // §6/F13: "keep for audit" (acknowledge) only applies to an ALREADY achieved
            // version (the backend 422s it otherwise) — pair it with link-replace.
            achieved -> {
                OutlinedButton(onClick = { onAction(DebtIntegrityAction.Acknowledge) }, enabled = !isSubmitting) {
                    Text(stringResource(R.string.debt_goal_review_action_keep))
                }
                Spacer(Modifier.width(AppSpacing.smallGap))
                Button(onClick = { onAction(DebtIntegrityAction.RemoveVoided) }, enabled = !isSubmitting) {
                    Text(stringResource(R.string.debt_goal_review_action_remove))
                }
            }
            // not_evaluable with a non-voided link to keep: link-replace removes the voided one.
            canRemoveVoided ->
                Button(onClick = { onAction(DebtIntegrityAction.RemoveVoided) }, enabled = !isSubmitting) {
                    Text(stringResource(R.string.debt_goal_review_action_remove))
                }
            // every link voided: no valid replacement set + no Debt picker this slice → archive.
            else ->
                Button(onClick = { onAction(DebtIntegrityAction.Archive) }, enabled = !isSubmitting) {
                    Text(stringResource(R.string.debt_goal_review_action_archive))
                }
        }
    }
}

/**
 * 详情屏的交互回调束（8e-6a 排序是会话级视图偏好；8e-6c 还清日期 picker 是屏级对话框，由 [DebtGoalScreen]
 * hoist）——打包成一个对象，让 [debtGoalDetailSection] 的参数数维持在 detekt LongParameterList 门内（≤5）。
 */
internal data class DebtGoalDetailCallbacks(
    val sortMode: DebtPlanSortMode,
    val onSortModeChange: (DebtPlanSortMode) -> Unit,
    val onSetTargetDate: () -> Unit,
)
