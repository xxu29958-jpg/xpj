package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.DisposableEffect
import com.ticketbox.ui.mascot.rememberMascotController
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import com.ticketbox.ui.components.AppPrimaryButton
import androidx.compose.material3.MaterialTheme
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.ui.components.AppOutlinedButtonOptions
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
import com.ticketbox.ui.screens.plan.GoalReadSource
import com.ticketbox.R
import com.ticketbox.domain.model.DebtGoalComposition
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.components.AppAdaptiveEditActionLayout
import com.ticketbox.ui.components.AppAdaptiveEditActionMode
import com.ticketbox.ui.components.AppAdaptiveMetricGrid
import com.ticketbox.ui.components.AppAdaptiveMetricGridCompactMinWidth
import com.ticketbox.ui.components.AppAdaptiveTrailingActionRow
import com.ticketbox.ui.components.AppListRow
import com.ticketbox.ui.components.AppListStateContent
import com.ticketbox.ui.components.AppListStateSpec
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryPageSlots
import com.ticketbox.ui.components.AppSecondaryRefreshState
import com.ticketbox.ui.components.AppSecondaryScrollableContent
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.AppFloatingActionBar
import com.ticketbox.ui.components.AppButtonIcons
import com.ticketbox.ui.components.AppAdaptiveContentActionRow
import com.ticketbox.ui.components.AppAdaptiveContentActionStyle
import com.ticketbox.ui.components.SettingsEntryIcon
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.outlined.Flag
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.TextButton
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.ui.screens.budget.MetricPill
import com.ticketbox.viewmodel.DebtGoalUiState
import com.ticketbox.viewmodel.DebtGoalViewModel
import kotlinx.coroutines.delay

/** 操作成功提示展示时长，到点自动收起（与 IncomePlanScreen 同惯例）。 */
private const val DebtGoalFlashDismissMillis = 4000L

/** The goal list and detail share the canonical read owner and retain their return context. */
@Composable
fun DebtGoalScreen(
    viewModel: DebtGoalViewModel,
    navigation: DebtGoalScreenNavigation,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val handleBack = {
        if (state.selectedGoal != null) viewModel.closeDetail() else navigation.onBack()
    }

    LaunchedEffect(state.flashMessage) {
        if (state.flashMessage == null) return@LaunchedEffect
        delay(DebtGoalFlashDismissMillis)
        viewModel.dismissFlash()
    }

    val selected = state.selectedGoal
    var confirmingArchive by rememberSaveable(selected?.publicId) { mutableStateOf(false) }
    // 「先清小的」排序是会话级视图偏好，跨 closeDetail 保留；日期由独立编辑任务保管。
    var sortMode by rememberSaveable { mutableStateOf(DebtPlanSortMode.Default) }
    val callbacks = DebtGoalScreenBodyCallbacks(
        handleBack = handleBack,
        onCreate = navigation.onCreate,
        hasCreationDraft = navigation.hasCreationDraft,
        association = navigation.association,
        onOpenLinkedDebt = navigation.onOpenLinkedDebt,
        onOpenRecycleBin = navigation.onOpenRecycleBin,
        detailCallbacks = DebtGoalDetailCallbacks(
            sortMode = sortMode,
            onSortModeChange = { sortMode = it },
            onSetTargetDate = { selected?.let { navigation.association.onDate(it.publicId) } },
            onEditLinks = { selected?.let { navigation.association.onOpen(it.publicId) } },
            onArchive = { confirmingArchive = true },
        ),
    )
    val mascot = rememberMascotController()
    val celebration by viewModel.celebration.collectAsStateWithLifecycle()
    // Leaving the displayed goal consumes any unfinished animation; reentry must not replay it.
    DisposableEffect(viewModel) { onDispose { viewModel.consumeCelebration(); viewModel.dismissFlash() } }
    Box(modifier = Modifier.fillMaxSize()) {
        DebtGoalScreenBody(state = state, viewModel = viewModel, callbacks = callbacks)
        DebtGoalCelebrationOverlay(celebration, mascot, viewModel::consumeCelebration)
    }
    if (confirmingArchive && selected != null && !selected.isArchived && state.canModify) {
        AlertDialog(
            onDismissRequest = { confirmingArchive = false },
            title = { Text(stringResource(R.string.debt_goal_archive_title)) },
            text = { Text(stringResource(R.string.debt_goal_archive_body)) },
            confirmButton = { TextButton(onClick = { confirmingArchive = false; viewModel.archiveSelected() },
                enabled = !state.isSubmitting) { Text(stringResource(R.string.spending_goal_archive_confirm)) } },
            dismissButton = { TextButton(onClick = { confirmingArchive = false }) { Text(stringResource(R.string.common_cancel)) } },
        )
    }
}

private data class DebtGoalScreenBodyCallbacks(
    val handleBack: () -> Unit,
    val onCreate: () -> Unit,
    val hasCreationDraft: Boolean,
    val association: DebtGoalEditNavigation,
    val onOpenLinkedDebt: (String) -> Unit,
    val onOpenRecycleBin: () -> Unit,
    val detailCallbacks: DebtGoalDetailCallbacks,
)

@Composable
private fun DebtGoalScreenBody(
    state: DebtGoalUiState,
    viewModel: DebtGoalViewModel,
    callbacks: DebtGoalScreenBodyCallbacks,
) {
    val selected = state.selectedGoal
    AppSecondaryScrollableContent(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Stats,
            title = selected?.name ?: stringResource(R.string.debt_goal_page_title),
            subtitle = if (selected == null) stringResource(R.string.debt_goal_intro_body) else null,
            backText = stringResource(if (selected == null) R.string.spending_goals_back_to_plan else R.string.debt_goal_topbar_title),
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
            bottomBar = if (selected == null && (state.canModify || callbacks.hasCreationDraft)) {
                { DebtGoalCreateAction(callbacks.hasCreationDraft, callbacks.onCreate) }
            } else null,
        ),
    ) {
        if (selected != null) {
            if (selected.isArchived) item {
                Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                    Text(stringResource(R.string.debt_goal_recovery_body), style = MaterialTheme.typography.bodyMedium)
                    if (state.canModify) TextButton(onClick = callbacks.onOpenRecycleBin) {
                        Text(stringResource(R.string.spending_goal_recovery_action))
                    }
                }
            }
            debtGoalDetailSection(
                state = state,
                viewModel = viewModel,
                onOpenLinkedDebt = callbacks.onOpenLinkedDebt,
                callbacks = callbacks.detailCallbacks,
            )
        } else {
            callbacks.association.retainedId?.let { id ->
                item { androidx.compose.material3.TextButton(onClick = { callbacks.association.onOpen(id) }) {
                    Text(stringResource(R.string.debt_goal_links_continue))
                } }
            }
            callbacks.association.retainedDateId?.let { id ->
                item { androidx.compose.material3.TextButton(onClick = { callbacks.association.onDate(id) }) {
                    Text(stringResource(R.string.debt_goal_date_continue))
                } }
            }
            debtGoalListSection(state = state, viewModel = viewModel, onOpenLinkedDebt = callbacks.onOpenLinkedDebt)
        }
    }
}

@Composable
private fun DebtGoalCreateAction(hasDraft: Boolean, onCreate: () -> Unit) {
    AppFloatingActionBar {
        AppPrimaryButton(text = stringResource(if (hasDraft) R.string.goal_draft_continue else R.string.debt_goal_create_cta),
            icons = AppButtonIcons(leading = Icons.Default.Add), modifier = Modifier.fillMaxWidth(), onClick = onCreate)
    }
}

@Composable
private fun DebtGoalStatusStack(state: DebtGoalUiState) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        if (!state.canModify) AppStatusBanner(message = com.ticketbox.domain.model.UiText.res(R.string.common_readonly_ledger),
            tone = MessageTone.Info, announceUpdates = false)
        GoalReadSource(
            if (state.selectedGoal != null) state.selectedFetchedAt else state.fetchedAt,
            if (state.selectedGoal != null) state.selectedFromCache else state.fromCache, state.isLoading)
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
    onOpenLinkedDebt: (String) -> Unit,
) {
    val active = state.goals.filterNot { it.isArchived }
    if (active.isEmpty()) item {
        AppListStateContent(state = AppListStateSpec(
            isEmpty = true, loading = state.isLoading,
            emptyText = stringResource(R.string.debt_goal_empty_body),
            emptyTitle = stringResource(R.string.debt_goal_empty_title),
            emptyBody = stringResource(R.string.debt_goal_empty_body),
        )) { }
    }
    active.forEach { goal ->
        item(key = goal.publicId) { DebtGoalListRow(goal, { viewModel.openDetail(goal) }, showDivider = false) }
        item { Text(stringResource(R.string.debt_goal_detail_links_title), style = MaterialTheme.typography.titleMedium) }
        val links = goal.debtRepayment?.linkedDebts.orEmpty()
        itemsIndexed(links, key = { _, link -> "${goal.publicId}:${link.debtPublicId}" }) { index, link ->
            DebtGoalLinkRow(link, onOpenLinkedDebt, showDivider = index < links.lastIndex)
        }
    }
    item {
        TextButton(onClick = { viewModel.setIncludeArchived(!state.includeArchived) }) {
            Text(stringResource(if (state.includeArchived) R.string.debt_goal_archived_hide else R.string.debt_goal_archived_show))
        }
    }
    if (state.includeArchived) item {
        DebtGoalOpenSection(title = stringResource(R.string.debt_goal_archived_title)) {
            val archived = state.goals.filter { it.isArchived }
            if (archived.isEmpty() && !state.isLoading) Text(stringResource(R.string.debt_goal_archived_empty))
            archived.forEachIndexed { index, goal ->
                DebtGoalListRow(goal, { viewModel.openDetail(goal) }, showDivider = index < archived.lastIndex)
            }
        }
    }
    if (active.isNotEmpty()) item {
        DebtGoalOpenSection(title = stringResource(R.string.debt_goal_overview_title)) {
            DebtGoalOverviewSection(debtGoalListSummary(active))
        }
    }
}

@Composable
private fun DebtGoalOverviewSection(summary: DebtGoalListSummary) {
    // 概况降为紧凑指标格：真正目标列表尽快进首屏，统计不再占半屏五行。
    val metrics = listOf(
        stringResource(R.string.debt_goal_metric_active) to
            stringResource(R.string.debt_goal_metric_goal_count, summary.activeGoalCount),
        stringResource(R.string.debt_goal_metric_achieved) to
            stringResource(R.string.debt_goal_metric_goal_count, summary.achievedGoalCount),
        stringResource(R.string.debt_goal_metric_review) to
            stringResource(R.string.debt_goal_metric_goal_count, summary.reviewGoalCount),
        stringResource(R.string.debt_goal_metric_linked_debts) to
            stringResource(R.string.debt_goal_metric_debt_count, summary.linkedDebtCount),
        stringResource(R.string.debt_goal_metric_open_debts) to
            stringResource(R.string.debt_goal_metric_debt_count, summary.openDebtCount),
    )
    AppAdaptiveMetricGrid(
        itemCount = metrics.size,
        twoColumnMinWidth = AppAdaptiveMetricGridCompactMinWidth,
    ) { index, metricModifier ->
        val (label, value) = metrics[index]
        MetricPill(label = label, value = value, modifier = metricModifier)
    }
}

@Composable
private fun DebtGoalListRow(
    goal: Goal,
    onClick: () -> Unit,
    showDivider: Boolean,
) {
    val evaluation = goal.debtRepayment
    AppListRow(onClick = onClick, settled = goal.isArchived || evaluation?.isAchieved == true, showDivider = showDivider) {
        AppAdaptiveContentActionRow(style = AppAdaptiveContentActionStyle(compactAction = true), content = {
            Row(verticalAlignment = Alignment.CenterVertically) {
                SettingsEntryIcon(Icons.Outlined.Flag)
                Spacer(Modifier.width(AppSpacing.compactGap))
                Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
                    Text(goal.name, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                    Text(listOfNotNull(stringResource(R.string.debt_goal_link_count, evaluation?.linkedDebts?.size ?: 0),
                        evaluation?.targetDate).joinToString(" · "), style = MaterialTheme.typography.bodySmall.tabularNum(),
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }, action = { actionModifier ->
            Row(modifier = actionModifier, verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
                if (goal.isArchived) Text(stringResource(R.string.debt_goal_archived_title), style = MaterialTheme.typography.labelMedium)
                else if (evaluation != null) DebtStatusBadge(
                    text = stringResource(debtGoalEvaluationLabelRes(evaluation.evaluationState)),
                    tone = debtGoalEvaluationTone(evaluation.evaluationState))
                Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null)
            }
        })
    }
}

private fun LazyListScope.debtGoalDetailSection(
    state: DebtGoalUiState,
    viewModel: DebtGoalViewModel,
    onOpenLinkedDebt: (String) -> Unit,
    callbacks: DebtGoalDetailCallbacks,
) {
    val goal = state.selectedGoal ?: return
    val evaluation = goal.debtRepayment ?: return
    val canModify = state.canModify && !goal.isArchived
    // §6 hero：件数为主视觉的关系进度卡（含状态徽章 + 达成态 + 8e-6c 纯外部债三态/还清日期/设日期入口）。
    item {
        DebtPlanProgressCard(
            evaluation = evaluation,
            canModify = canModify,
            onSetTargetDate = callbacks.onSetTargetDate,
        )
    }
    if (evaluation.needsReview) {
        item {
            DebtGoalIntegrityReviewCard(
                achieved = evaluation.isAchieved,
                canRemoveVoided = evaluation.nonVoidedDebtPublicIds.isNotEmpty(),
                canModify = canModify,
                isSubmitting = state.isSubmitting,
                onAction = { action ->
                    when (action) {
                        DebtIntegrityAction.Acknowledge -> viewModel.acknowledge()
                        DebtIntegrityAction.RemoveVoided -> callbacks.onEditLinks()
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
        ) {
            if (canModify) {
                androidx.compose.material3.TextButton(onClick = callbacks.onEditLinks) {
                    Text(stringResource(R.string.debt_goal_links_action))
                }
            }
            if (isPureExternal) {
                DebtPlanSortToggle(mode = callbacks.sortMode, onModeChange = callbacks.onSortModeChange)
            }
        }
    }
    val links =
        if (isPureExternal) evaluation.linkedDebts.sortedForPlan(callbacks.sortMode) else evaluation.linkedDebts
    itemsIndexed(links, key = { _, link -> link.debtPublicId }) { index, link ->
        DebtGoalLinkRow(
            link = link,
            onClick = onOpenLinkedDebt,
            showDivider = index < links.lastIndex,
        )
    }
    if (canModify) item {
        TextButton(onClick = callbacks.onArchive, enabled = !state.isSubmitting) {
            Text(stringResource(R.string.debt_goal_review_action_archive))
        }
    }
}

/** The §6/F13 integrity-review exits the UI can offer (mapped to VM actions). */
internal enum class DebtIntegrityAction { Acknowledge, RemoveVoided }

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
    val keepAction: @Composable (Modifier) -> Unit = { actionModifier ->
        AppOutlinedButton(
            modifier = actionModifier,
            onClick = { onAction(DebtIntegrityAction.Acknowledge) },
            options = AppOutlinedButtonOptions(enabled = !isSubmitting),
        ) {
            Text(stringResource(R.string.debt_goal_review_action_keep))
        }
    }
    val removeAction: @Composable (Modifier) -> Unit = { actionModifier ->
        AppPrimaryButton(
            text = stringResource(R.string.debt_goal_review_action_remove),
            modifier = actionModifier,
            onClick = { onAction(DebtIntegrityAction.RemoveVoided) },
            enabled = !isSubmitting,
        )
    }
    when {
        // §6/F13: "keep for audit" (acknowledge) only applies to an ALREADY achieved
        // version (the backend 422s it otherwise) — pair it with link-replace.
        achieved -> AppAdaptiveEditActionLayout(
            actionCount = 2,
            compact = false,
            stackTwoActionsOnNarrow = true,
        ) { mode ->
            when (mode) {
                AppAdaptiveEditActionMode.Stacked -> Column(
                    modifier = Modifier.fillMaxWidth(),
                    verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
                ) {
                    keepAction(Modifier.fillMaxWidth())
                    removeAction(Modifier.fillMaxWidth())
                }

                AppAdaptiveEditActionMode.Compact,
                AppAdaptiveEditActionMode.Inline -> Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap, Alignment.End),
                ) {
                    keepAction(Modifier)
                    removeAction(Modifier)
                }
            }
        }
        // not_evaluable with a non-voided link to keep: link-replace removes the voided one.
        canRemoveVoided -> AppAdaptiveTrailingActionRow { actionModifier -> removeAction(actionModifier) }
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
    val onEditLinks: () -> Unit,
    val onArchive: () -> Unit,
)
