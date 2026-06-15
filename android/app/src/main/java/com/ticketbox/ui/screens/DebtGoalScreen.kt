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
import com.ticketbox.domain.model.DebtGoalLink
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
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
private fun DebtGoalHeader(title: String, subtitle: String?, onBack: () -> Unit) {
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
        AppPageHeader(title = title, subtitle = subtitle)
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
                        color = MaterialTheme.colorScheme.error,
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
    item { DebtGoalSummaryCard(goal) }
    if (evaluation.needsReview) {
        item {
            DebtGoalIntegrityReviewCard(
                achieved = evaluation.isAchieved,
                canModify = state.canModify,
                isSubmitting = state.isSubmitting,
                onRemoveVoided = viewModel::removeVoidedDebts,
                onAcknowledge = viewModel::acknowledge,
            )
        }
    }
    item { SectionEyebrow(stringResource(R.string.debt_goal_detail_links_title)) }
    items(evaluation.linkedDebts, key = { it.debtPublicId }) { link ->
        DebtLinkRow(link = link, currency = currency)
    }
}

@Composable
private fun DebtGoalSummaryCard(goal: Goal) {
    val evaluation = goal.debtRepayment ?: return
    AppGlassCard(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(AppSpacing.cardPadding)) {
            DebtStatusBadge(
                text = stringResource(debtGoalEvaluationLabelRes(evaluation.evaluationState)),
                tone = debtGoalEvaluationTone(evaluation.evaluationState),
            )
            if (evaluation.isAchieved) {
                Spacer(Modifier.size(AppSpacing.smallGap))
                Text(
                    stringResource(R.string.debt_goal_detail_achieved_hint),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                )
            }
        }
    }
}

@Composable
private fun DebtGoalIntegrityReviewCard(
    achieved: Boolean,
    canModify: Boolean,
    isSubmitting: Boolean,
    onRemoveVoided: () -> Unit,
    onAcknowledge: () -> Unit,
) {
    AppGlassCard(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(AppSpacing.cardPadding)) {
            Text(
                stringResource(R.string.debt_goal_review_title),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.error,
            )
            Spacer(Modifier.size(AppSpacing.miniGap))
            Text(
                stringResource(
                    if (achieved) R.string.debt_goal_review_body_achieved
                    else R.string.debt_goal_review_body_not_evaluable,
                ),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (canModify) {
                Spacer(Modifier.size(AppSpacing.compactGap))
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                    OutlinedButton(onClick = onAcknowledge, enabled = !isSubmitting) {
                        Text(stringResource(R.string.debt_goal_review_action_keep))
                    }
                    Spacer(Modifier.width(AppSpacing.smallGap))
                    Button(onClick = onRemoveVoided, enabled = !isSubmitting) {
                        Text(stringResource(R.string.debt_goal_review_action_remove))
                    }
                }
            }
        }
    }
}

@Composable
private fun DebtLinkRow(link: DebtGoalLink, currency: CurrencyDisplay) {
    AppGlassCard(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(AppSpacing.cardPadding)) {
            Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text(
                    debtLinkCounterparty(link),
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.weight(1f),
                )
                DebtStatusBadge(
                    text = stringResource(debtLinkStatusLabelRes(link.status)),
                    tone = debtLinkStatusTone(link.status),
                )
            }
            Spacer(Modifier.size(AppSpacing.miniGap))
            Text(
                stringResource(
                    R.string.debt_goal_link_meta,
                    stringResource(debtDirectionLabelRes(link.direction)),
                    formatDisplayAmount(link.remainingAmountCents, currency),
                    formatDisplayAmount(link.principalAmountCents, currency),
                ),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
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
