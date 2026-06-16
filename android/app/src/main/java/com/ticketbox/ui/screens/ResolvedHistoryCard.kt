package com.ticketbox.ui.screens

import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.MemberProposalStatuses
import com.ticketbox.domain.model.MemberRepaymentProposal
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.displayDate
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.tabularNum

/**
 * ADR-0049 §7.0 (slice 8e ③) "过往" —— 成员债收发箱底部的**已解决** proposal 沉降列表 (在途 pending 由上方
 * [MemberProposalSection] 的债务人/债权人卡承载，§3.2 不进历史，避免一件事出现两次)。研究背书：累积可见的
 * scorecard 会把关系重分类为 Market (Gladstone / Clark & Mills)。故沉降态**逐条清晰**(金额/状态/日期/备注)
 * 但**集合零汇总**——无 total/count/rank、所有已解决态一律 neutral 灰、不给成功行挑亮 (§3.4 去 success 竖条)。
 * 视觉降权全用既有 token 的 [AppAlpha] 叠 (三主题自动一致，不硬编码浅色)；日期到"日"不到分秒 (去对账味)。
 */
private const val RESOLVED_HISTORY_COLLAPSED_COUNT = 3

@Composable
internal fun ResolvedHistoryCard(resolved: List<MemberRepaymentProposal>, currency: CurrencyDisplay) {
    var expanded by rememberSaveable { mutableStateOf(false) }
    val shown = if (expanded) resolved else resolved.take(RESOLVED_HISTORY_COLLAPSED_COUNT)
    // Recession (§3.3) is carried per-row (sunk type/color + per-element alphas below); the card keeps a
    // normal glass container so it stays legible — stacking a whole-card alpha on top would compound with
    // the row alphas and risk the midnight contrast the design flagged.
    AppGlassCard(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(AppSpacing.cardPadding),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        ) {
            Text(
                stringResource(R.string.debt_proposal_history_past_title),
                style = MaterialTheme.typography.labelSmall,
                color = LocalStateTokens.current.neutral.fg,
            )
            shown.forEach { proposal -> ResolvedProposalRow(proposal = proposal, currency = currency) }
            if (resolved.size > RESOLVED_HISTORY_COLLAPSED_COUNT) {
                HistoryExpandToggle(total = resolved.size, expanded = expanded, onToggle = { expanded = !expanded })
            }
        }
    }
}

@Composable
private fun HistoryExpandToggle(total: Int, expanded: Boolean, onToggle: () -> Unit) {
    TextButton(onClick = onToggle) {
        Text(
            if (expanded) {
                stringResource(R.string.debt_proposal_history_collapse)
            } else {
                stringResource(R.string.debt_proposal_history_expand, total)
            },
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun ResolvedProposalRow(proposal: MemberRepaymentProposal, currency: CurrencyDisplay) {
    Row(
        modifier = Modifier.fillMaxWidth().alpha(AppAlpha.opaque),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                formatDisplayAmount(proposal.proposedAmountCents, currency),
                style = MaterialTheme.typography.bodySmall.tabularNum(),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            proposal.note?.takeIf { it.isNotBlank() }?.let { note ->
                Text(
                    note,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = AppAlpha.heavy),
                )
            }
            Text(
                resolvedDateText(proposal),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = AppAlpha.medium),
            )
        }
        // §3.4 已解决态一律 neutral (confirmed 不再挑成 success)；容器再 alpha(heavy) 沉一档。
        Box(modifier = Modifier.alpha(AppAlpha.heavy)) {
            DebtStatusBadge(
                text = stringResource(memberProposalStatusLabelRes(proposal.status)),
                tone = LocalStateTokens.current.neutral,
            )
        }
    }
}

/** 解决日期前缀：仅 confirmed (全额两清) 标"对上"、partial 专属"收了一部分"、其余纯日期不加负面前缀 (§3.7)。 */
@Composable
private fun resolvedDateText(proposal: MemberRepaymentProposal): String {
    val day = displayDate(proposal.resolvedAt ?: proposal.createdAt)
    return when (proposal.status) {
        MemberProposalStatuses.CONFIRMED -> stringResource(R.string.debt_proposal_history_resolved_date, day)
        MemberProposalStatuses.PARTIALLY_CONFIRMED -> stringResource(R.string.debt_proposal_history_partial_date, day)
        else -> stringResource(R.string.debt_proposal_history_closed_date, day)
    }
}

/** ADR-0049 §3.2 (slice 8d) member repayment-proposal status → localized label (8e ③ 搬来沉降历史专用)。 */
@StringRes
private fun memberProposalStatusLabelRes(status: String): Int = when (status) {
    MemberProposalStatuses.PENDING -> R.string.debt_proposal_status_pending
    MemberProposalStatuses.CONFIRMED -> R.string.debt_proposal_status_confirmed
    MemberProposalStatuses.PARTIALLY_CONFIRMED -> R.string.debt_proposal_status_partially_confirmed
    MemberProposalStatuses.REJECTED -> R.string.debt_proposal_status_rejected
    MemberProposalStatuses.WITHDRAWN -> R.string.debt_proposal_status_withdrawn
    MemberProposalStatuses.EXPIRED -> R.string.debt_proposal_status_expired
    MemberProposalStatuses.SUPERSEDED -> R.string.debt_proposal_status_superseded
    else -> R.string.debt_proposal_status_pending
}
