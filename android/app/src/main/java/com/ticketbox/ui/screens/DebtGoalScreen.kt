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
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
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
 * 复用共享骨架（[AppScrollableContent] + [AppPageHeader] + [AppGlassCard] +
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
    AppScrollableContent(
        role = AppPageRole.Stats,
        isRefreshing = state.isLoading,
        onRefresh = viewModel::refresh,
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
            debtGoalDetailSection(state = state, currency = currency, viewModel = viewModel)
        } else {
            debtGoalListSection(state = state, viewModel = viewModel)
        }
    }
}

@Composable
private fun DebtGoalHeader(
    title: String,
    subtitle: String?,
    onBack: () -> Unit,
    onCreate: (() -> Unit)?,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        TextButton(onClick = onBack) {
            Icon(
                Icons.AutoMirrored.Filled.ArrowBack,
                contentDescription = stringResource(R.string.debt_goal_topbar_back),
                modifier = Modifier.size(18.dp),
            )
            Spacer(Modifier.width(4.dp))
            Text(stringResource(R.string.debt_goal_topbar_back))
        }
        AppPageHeader(title = title, subtitle = subtitle) {
            if (onCreate != null) {
                PrimaryCtaButton(
                    text = stringResource(R.string.debt_goal_create_cta),
                    icon = Icons.Default.Add,
                    onClick = onCreate,
                )
            }
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
) {
    val goal = state.selectedGoal ?: return
    val evaluation = goal.debtRepayment ?: return
    // §6 hero：件数为主视觉的关系进度卡（含状态徽章 + 达成态），取代旧的纯状态摘要卡。
    item { DebtPlanProgressCard(evaluation = evaluation, currency = currency) }
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
    items(evaluation.linkedDebts, key = { it.debtPublicId }) { link ->
        DebtGoalLinkRow(link = link, currency = currency)
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
