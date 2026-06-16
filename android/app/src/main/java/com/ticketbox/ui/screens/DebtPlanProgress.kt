package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtGoalComposition
import com.ticketbox.domain.model.DebtGoalLink
import com.ticketbox.domain.model.DebtRepaymentEvaluation
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.AppProgressBar
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.tabularNum

/**
 * ADR-0049 §6 (slice 8e-5) 还债目标进度 —— **Communal Pay-Down，不是还债引擎**。把 slice7 的纯「评估状态表」
 * 升级成「件数为主视觉 + 一句关系话」的进度视图（[DebtPlanProgressCard] 计划级 + [DebtGoalLinkRow] 每笔级）。
 *
 * 硬收窄（§6 前置）：成员债**无清偿排序器 / 无三态 / 无还清日期投影 / 无单笔撒花 / 无百分比里程碑催促**——
 * 那些是 Market 心智模型的债务仪表盘。进度按**笔数**填充（一格=一笔=一次两清），金额降到小字副文案且
 * **永不带「欠」字**、混币整条隐藏（§6.2）。成分自适应语气（§6.7）：成员关系化、外部会计化、混装降级中性。
 * 角色框架（§6.1 / backend F7）：进度/件数/金额全是冻结快照的纯客户端算术（[DebtRepaymentEvaluation] 上的
 * 派生属性），**不引入客户端 viewer_is_debtor 推导**（红线⑥）。达成撒花只读服务端 evaluation_state（§6.6，
 * 在 [com.ticketbox.viewmodel.DebtGoalViewModel] + [DebtGoalCelebrationOverlay]），这里只做进度渲染。
 *
 * 独立成文件（不堆进 [DebtGoalScreen]，后者已在文件级 TooManyFunctions 门附近，[[project_android_compose_detekt_limits]]）。
 */
@Composable
internal fun DebtPlanProgressCard(
    evaluation: DebtRepaymentEvaluation,
    currency: CurrencyDisplay,
    canModify: Boolean,
    onSetTargetDate: () -> Unit,
) {
    AppGlassCard(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(AppSpacing.cardPadding)) {
            DebtStatusBadge(
                text = stringResource(debtGoalEvaluationLabelRes(evaluation.evaluationState)),
                tone = debtGoalEvaluationTone(evaluation.evaluationState),
            )
            Spacer(Modifier.size(AppSpacing.smallGap))
            if (evaluation.totalCount == 0) {
                // 全部关联欠款已作废（§6.2 空态）：不渲染进度条，短路到下方复核卡 / 空状态。
                Text(
                    stringResource(R.string.debt_plan_all_voided),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                PlanCountHeadline(evaluation)
                Spacer(Modifier.size(AppSpacing.compactGap))
                AppProgressBar(
                    fraction = evaluation.planFraction,
                    tone = LocalStateTokens.current.success,
                    height = AppSpacing.contentGap,
                    contentDescription = stringResource(
                        R.string.debt_plan_progress_a11y,
                        evaluation.clearedCount,
                        evaluation.totalCount,
                    ),
                )
                if (evaluation.sharedHomeCurrencyCode != null) {
                    Spacer(Modifier.size(AppSpacing.smallGap))
                    PlanAmountLine(evaluation, currency)
                }
                // 8e-6b/6c：还清日期投影 + 三态 + 设/改还清日期只对**纯外部债**计划呈现（§7.0 红线：成员/
                // 混装不做 Market 还债仪表盘；gate 用 `== External` 不是 `!= Member` 以排除 Mixed）。服务端已
                // gate，这是冗余第二层防线——也保证「设还清日期」入口永不泄漏到成员/混装计划（picker 红线）。
                if (evaluation.composition == DebtGoalComposition.External) {
                    Spacer(Modifier.size(AppSpacing.smallGap))
                    DebtExternalKpiBlock(
                        evaluation = evaluation,
                        canModify = canModify,
                        onSetTargetDate = onSetTargetDate,
                    )
                }
            }
        }
    }
}

/**
 * 外部债 KPI 块（§7.0 / 8e-6b+6c，**纯外部债**）：三态徽章（只在服务端给出 `three_state` 时显）+ 还清目标
 * 截止日（月粒度）+ 还清日期投影（节奏估算 / 数据不足中性文案）+ 设/改还清日期入口（可写时）。
 *
 * **去-shame 红线（§7.0）**：三态 at_risk = 事实性「晚于计划」，色调走 **warn（琥珀）非 danger/红**
 * （见 [debtThreeStateTone]），文案非第二人称指责、不催「更快还清」。设还清日期入口只在本块出现，而本块只对
 * `composition == External` 渲染（调用方 gate），故 picker 永不泄漏到成员/混装计划（设计对抗审红线）。
 */
@Composable
private fun DebtExternalKpiBlock(
    evaluation: DebtRepaymentEvaluation,
    canModify: Boolean,
    onSetTargetDate: () -> Unit,
) {
    val threeState = evaluation.threeState
    val targetYearMonth = evaluation.targetDate?.let { parsePayoffYearMonth(it) }
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        if (threeState != null) {
            DebtStatusBadge(
                text = stringResource(debtThreeStateLabelRes(threeState)),
                tone = debtThreeStateTone(threeState),
            )
        }
        if (targetYearMonth != null) {
            Text(
                stringResource(R.string.debt_goal_target_label, targetYearMonth.first, targetYearMonth.second),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        DebtPayoffProjectionLine(evaluation)
        if (canModify) {
            DebtSetTargetDateButton(hasDeadline = evaluation.targetDate != null, onClick = onSetTargetDate)
        }
    }
}

/** 还清日期投影行（§7.0 / 8e-6b）：节奏估算「按最近 N 天，预计 YYYY年M月前后还清」/ 数据不足中性文案。 */
@Composable
private fun DebtPayoffProjectionLine(evaluation: DebtRepaymentEvaluation) {
    val yearMonth = evaluation.projectedPayoffDate?.let { parsePayoffYearMonth(it) }
    val trackingDays = evaluation.trackingDays
    val text = if (yearMonth != null && trackingDays != null) {
        stringResource(R.string.debt_kpi_payoff, trackingDays, yearMonth.first, yearMonth.second)
    } else {
        stringResource(R.string.debt_kpi_payoff_unknown)
    }
    Text(
        text,
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
}

/** 设/改还清日期入口（低调 TextButton）：有截止日时「修改」、否则「设置」；点击交调用方打开 date picker。 */
@Composable
private fun DebtSetTargetDateButton(hasDeadline: Boolean, onClick: () -> Unit) {
    TextButton(onClick = onClick, contentPadding = PaddingValues(0.dp)) {
        Text(
            stringResource(
                if (hasDeadline) R.string.debt_goal_edit_target_date else R.string.debt_goal_set_target_date,
            ),
            style = MaterialTheme.typography.labelMedium,
        )
    }
}

/** 计划级件数主文案（大字，tabularNum）：成分自适应——成员关系化、外部/混装会计化（§6.2 / §6.7）。 */
@Composable
private fun PlanCountHeadline(evaluation: DebtRepaymentEvaluation) {
    val text = when (evaluation.composition) {
        DebtGoalComposition.Member -> when {
            evaluation.clearedCount == 0 -> stringResource(R.string.debt_plan_headline_member_start)
            evaluation.remainingCount == 0 -> stringResource(R.string.debt_plan_headline_member_done)
            else -> stringResource(
                R.string.debt_plan_headline_member,
                evaluation.clearedCount,
                evaluation.remainingCount,
            )
        }
        DebtGoalComposition.External -> stringResource(
            R.string.debt_plan_headline_external,
            evaluation.clearedCount,
            evaluation.totalCount,
        )
        // 混装：降级中性会计语气（§6.7，避免成员债被外部债的 businesslike 味污染，也不给信用卡撒花）。
        DebtGoalComposition.Mixed -> stringResource(
            R.string.debt_plan_headline_mixed,
            evaluation.clearedCount,
            evaluation.totalCount,
        )
        // 不可达：totalCount==0 已在调用方短路（防御性兜底）。
        DebtGoalComposition.Empty -> stringResource(R.string.debt_plan_all_voided)
    }
    Text(
        text,
        style = MaterialTheme.typography.titleMedium.tabularNum(),
        fontWeight = FontWeight.SemiBold,
        color = MaterialTheme.colorScheme.onSurface,
    )
}

/** 金额副文案（小字弱化，tabularNum）：仅同一本位币时显示（混币整条隐藏由调用方守）；成员**永不带「欠」字**（§6.2）。 */
@Composable
private fun PlanAmountLine(evaluation: DebtRepaymentEvaluation, currency: CurrencyDisplay) {
    val total = formatDisplayAmount(evaluation.principalSumCents, currency)
    val remaining = formatDisplayAmount(evaluation.remainingSumCents, currency)
    val isMember = evaluation.composition == DebtGoalComposition.Member
    val text = when {
        evaluation.remainingCount == 0 ->
            if (isMember) {
                stringResource(R.string.debt_plan_amount_member_done, total)
            } else {
                stringResource(R.string.debt_plan_amount_external_done, total)
            }
        isMember -> stringResource(R.string.debt_plan_amount_member, total, remaining)
        else -> stringResource(R.string.debt_plan_amount_external, total, remaining)
    }
    Text(
        text,
        style = MaterialTheme.typography.bodySmall.tabularNum(),
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
}

/**
 * 每笔关联欠款行（§6.2 每笔级 + §6.7 逐行成分自适应）：对手方 + 状态徽章 + 4dp 迷你进度条 + 一句话。
 * 进度条填充 success（两清）/ neutral（进行中），**绝不 danger**（红线②）；作废行不显进度条、整行 alpha 沉降
 * （§6.5「这件事不算了」是平静收束不是错误）。成员行走暖语（[memberDebtStatusLabelRes] / [memberDebtProgressNoteRes]），
 * 外部行走会计 meta（应付/应收 · 剩余 · 本金）——天然处理混装计划（逐行按各自类型措辞）。
 */
@Composable
internal fun DebtGoalLinkRow(link: DebtGoalLink, currency: CurrencyDisplay) {
    val isMember = link.counterpartyType == DebtCounterpartyTypes.MEMBER
    val cardModifier = if (link.isVoided) {
        Modifier.fillMaxWidth().alpha(AppAlpha.opaque)
    } else {
        Modifier.fillMaxWidth()
    }
    AppGlassCard(modifier = cardModifier) {
        Column(modifier = Modifier.padding(AppSpacing.cardPadding)) {
            Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text(
                    debtLinkCounterparty(link),
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.weight(1f),
                )
                if (isMember) {
                    DebtStatusBadge(
                        text = stringResource(memberDebtStatusLabelRes(link.status)),
                        tone = memberDebtStatusTone(link.status),
                    )
                } else {
                    DebtStatusBadge(
                        text = stringResource(debtLinkStatusLabelRes(link.status)),
                        tone = debtLinkStatusTone(link.status),
                    )
                }
            }
            if (!link.isVoided) {
                Spacer(Modifier.size(AppSpacing.smallGap))
                AppProgressBar(
                    fraction = link.clearedFraction,
                    tone = if (link.isCleared) {
                        LocalStateTokens.current.success
                    } else {
                        LocalStateTokens.current.neutral
                    },
                    height = AppSpacing.miniGap,
                )
            }
            Spacer(Modifier.size(AppSpacing.smallGap))
            DebtGoalLinkNote(link = link, currency = currency, isMember = isMember)
        }
    }
}

/** 每笔行的一句话：成员行暖语（已两清 / 进度程度语 / 这件事不算了），外部行会计 meta。 */
@Composable
private fun DebtGoalLinkNote(link: DebtGoalLink, currency: CurrencyDisplay, isMember: Boolean) {
    if (isMember) {
        val res = when {
            link.isVoided -> R.string.debt_link_member_note_voided
            link.isCleared -> R.string.debt_link_member_note_cleared
            else -> memberDebtProgressNoteRes(link.clearedFraction)
        }
        Text(
            stringResource(res),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    } else {
        Text(
            stringResource(
                R.string.debt_goal_link_meta,
                stringResource(debtDirectionLabelRes(link.direction)),
                formatDisplayAmount(link.remainingAmountCents, currency),
                formatDisplayAmount(link.principalAmountCents, currency),
            ),
            style = MaterialTheme.typography.bodySmall.tabularNum(),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}
