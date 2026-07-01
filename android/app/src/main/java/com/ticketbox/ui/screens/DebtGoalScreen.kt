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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.Button
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberDatePickerState
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
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.DebtGoalComposition
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.AppSecondaryPageHeader
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.PrimaryCtaButton
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens
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
 * 复用共享骨架（[AppScrollableContent] + secondary header + [AppGlassCard] +
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

    BackHandler(onBack = handleBack)

    val selected = state.selectedGoal
    // 8e-6a「先清小的」排序 + 8e-6c 还清日期 picker 显隐：详情层 composable-local 视图态（无持久化/无 DataStore；
    // 排序刻意不 keyed-by-goal=会话级视图偏好，跨 closeDetail 保留）。picker 对话框在 AppScrollableContent **外**渲染。
    var sortMode by rememberSaveable { mutableStateOf(DebtPlanSortMode.Default) }
    var showDatePicker by rememberSaveable { mutableStateOf(false) }
    AppScrollableContent(
        role = AppPageRole.Stats,
        isRefreshing = state.isLoading,
        // 不能用 viewModel::refresh：refresh 现带 clearStale 默认参，方法引用解析为 (Boolean)->Unit 不匹配 ()->Unit。
        onRefresh = { viewModel.refresh() },
        hasBottomBar = false,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
    ) {
        item {
            DebtGoalHeader(
                title = selected?.name ?: stringResource(R.string.debt_goal_topbar_title),
                subtitle = if (selected == null) stringResource(R.string.debt_goal_intro_body) else null,
                onBack = handleBack,
                // CTA 仅在列表态（非详情）且可写时出现；创建走 onCreate（overlay 内子页）。
                onCreate = if (selected == null && state.canModify) onCreate else null,
            )
        }
        state.flashMessage?.let { msg ->
            item { AppStatusBanner(message = msg, tone = MessageTone.Success) }
        }
        state.error?.let { err ->
            item { AppStatusBanner(message = err, tone = MessageTone.Danger) }
        }
        if (selected != null) {
            debtGoalDetailSection(
                state = state,
                currency = currency,
                viewModel = viewModel,
                onOpenLinkedDebt = onOpenLinkedDebt,
                callbacks = DebtGoalDetailCallbacks(
                    sortMode = sortMode,
                    onSortModeChange = { sortMode = it },
                    onSetTargetDate = { showDatePicker = true },
                ),
            )
        } else {
            debtGoalListSection(state = state, viewModel = viewModel)
        }
    }
    DebtTargetDatePickerDialog(
        visible = showDatePicker,
        selected = selected,
        onSetTargetDate = viewModel::setTargetDate,
        onDismiss = { showDatePicker = false },
    )
}

@Composable
private fun DebtGoalHeader(
    title: String,
    subtitle: String?,
    onBack: () -> Unit,
    onCreate: (() -> Unit)?,
) {
    AppSecondaryPageHeader(
        title = title,
        subtitle = subtitle,
        backText = stringResource(R.string.debt_goal_topbar_back),
        onBack = onBack,
    ) {
        if (onCreate != null) {
            PrimaryCtaButton(
                text = stringResource(R.string.debt_goal_create_cta),
                icon = Icons.Default.Add,
                onClick = onCreate,
            )
        }
    }
}

private fun LazyListScope.debtGoalListSection(
    state: DebtGoalUiState,
    viewModel: DebtGoalViewModel,
) {
    if (state.goals.isEmpty() && !state.isLoading) {
        item { DebtGoalEmptyCard() }
        return
    }
    items(state.goals, key = { it.publicId }) { goal ->
        DebtGoalListCard(goal = goal, onClick = { viewModel.openDetail(goal) })
    }
}

@Composable
private fun DebtGoalListCard(goal: Goal, onClick: () -> Unit) {
    val evaluation = goal.debtRepayment
    AppGlassCard(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable(onClick = onClick)
                .padding(AppSpacing.cardPadding),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    goal.name,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                )
                Spacer(Modifier.size(AppSpacing.miniGap))
                Text(
                    stringResource(
                        R.string.debt_goal_card_linked_count,
                        evaluation?.linkedDebts?.size ?: 0,
                    ),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Column(horizontalAlignment = Alignment.End) {
                if (evaluation != null) {
                    DebtStatusBadge(
                        text = stringResource(debtGoalEvaluationLabelRes(evaluation.evaluationState)),
                        tone = debtGoalEvaluationTone(evaluation.evaluationState),
                    )
                }
                if (evaluation?.needsReview == true) {
                    Spacer(Modifier.size(AppSpacing.miniGap))
                    Text(
                        stringResource(R.string.debt_goal_card_needs_review),
                        style = MaterialTheme.typography.labelSmall,
                        // §6.5 去 shame：复核是「需要你拿个主意」的注意态，不是错误——用 warn（琥珀）非 error（红）。
                        color = LocalStateTokens.current.warn.fg,
                    )
                }
            }
        }
    }
}

@Composable
private fun DebtGoalEmptyCard() {
    AppGlassCard(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(AppSpacing.sectionGap),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                stringResource(R.string.debt_goal_empty_title),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
            Spacer(Modifier.size(AppSpacing.smallGap))
            Text(
                stringResource(R.string.debt_goal_empty_body),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
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
    item { SectionEyebrow(stringResource(R.string.debt_goal_detail_links_title)) }
    // 8e-6a：「先清小的」排序只对**纯外部债**开放（§7.0 红线，成员/混装不做清偿排序器）。
    // 必须用 `== External`（`!= Member` 会误纳 Mixed）。排序对**冻结快照**纯客户端算术、返回新列表，
    // `items(key = debtPublicId)` 因稳定 key 平滑重组（不改源 list，对抗审 C2）。
    val isPureExternal = evaluation.composition == DebtGoalComposition.External
    if (isPureExternal) {
        item { DebtPlanSortToggle(mode = callbacks.sortMode, onModeChange = callbacks.onSortModeChange) }
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
    AppGlassCard(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(AppSpacing.cardPadding)) {
            Text(
                stringResource(R.string.debt_goal_review_title),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
                // §6.5 去 shame：复核标题用 warn（琥珀）非 error（红），保持暖意红线。
                color = LocalStateTokens.current.warn.fg,
            )
            Spacer(Modifier.size(AppSpacing.miniGap))
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
                Spacer(Modifier.size(AppSpacing.compactGap))
                DebtGoalIntegrityActions(
                    achieved = achieved,
                    canRemoveVoided = canRemoveVoided,
                    isSubmitting = isSubmitting,
                    onAction = onAction,
                )
            }
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
 * 详情屏的交互回调束（8e-6a 排序是会话级视图偏好；8e-6c 还清日期 picker 是屏级对话框，由 [DebtGoalScreen]
 * hoist）——打包成一个对象，让 [debtGoalDetailSection] 的参数数维持在 detekt LongParameterList 门内（≤5）。
 */
internal data class DebtGoalDetailCallbacks(
    val sortMode: DebtPlanSortMode,
    val onSortModeChange: (DebtPlanSortMode) -> Unit,
    val onSetTargetDate: () -> Unit,
)

/**
 * 8e-6c 还清日期 picker（Material3 [DatePickerDialog]）。[visible] 为 false 时 no-op（host 逻辑内联于此，避免在
 * [DebtGoalScreen] 体内占行触 LongMethod）。确定=用选中的 UTC 毫秒设截止日；[selected] 已有截止日时额外给
 * 「清除日期」（=清空，走 `onSetTargetDate(null)`）。picker 初值回显当前截止日。**不限制过去日期**：过去截止日是
 * 合法输入（→ at_risk，事实性「晚于计划」，钉死在后端 `test_three_state_at_risk_when_deadline_is_in_the_past`）。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DebtTargetDatePickerDialog(
    visible: Boolean,
    selected: Goal?,
    onSetTargetDate: (Long?) -> Unit,
    onDismiss: () -> Unit,
) {
    // R2 defense-in-depth (§7.0)：还清日期入口本就只从 DebtExternalKpiBlock（composition == External）可达，
    // 但 render 层再 gate 一道——即便 hoist 的 showDatePicker 跨 goal 切换残留到成员/混装计划，picker 也 no-op。
    if (!visible || selected?.debtRepayment?.composition != DebtGoalComposition.External) return
    // `selected` is smart-cast non-null here (the guard returns on null/non-External).
    val deadlineIso = selected.debtRepayment?.targetDate
    val pickerState = rememberDatePickerState(
        initialSelectedDateMillis = deadlineIso?.let { isoDateToEpochMillis(it) },
    )
    DatePickerDialog(
        onDismissRequest = onDismiss,
        confirmButton = {
            TextButton(
                onClick = { pickerState.selectedDateMillis?.let { onSetTargetDate(it); onDismiss() } },
                enabled = pickerState.selectedDateMillis != null,
            ) { Text(stringResource(R.string.common_confirm)) }
        },
        dismissButton = {
            Row {
                if (deadlineIso != null) {
                    TextButton(onClick = { onSetTargetDate(null); onDismiss() }) {
                        Text(stringResource(R.string.debt_goal_target_date_clear))
                    }
                }
                TextButton(onClick = onDismiss) { Text(stringResource(R.string.common_cancel)) }
            }
        },
    ) {
        DatePicker(
            state = pickerState,
            title = {
                Text(
                    stringResource(R.string.debt_goal_target_date_picker_title),
                    modifier = Modifier.padding(start = 24.dp, end = 12.dp, top = 16.dp),
                )
            },
        )
    }
}
