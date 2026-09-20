package com.ticketbox.ui.screens

import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.relocation.BringIntoViewRequester
import androidx.compose.foundation.relocation.bringIntoViewRequester
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.DebtActivity
import com.ticketbox.domain.model.FxContract
import com.ticketbox.domain.model.MemberProposalStatuses
import com.ticketbox.domain.model.MemberRepaymentProposal
import com.ticketbox.ui.components.AppListRow
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.displayDateTime
import com.ticketbox.ui.components.displayDate
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing

internal data class DebtActivityRowState(
    val event: DebtActivity,
    val homeCurrencyCode: String?,
    val showDivider: Boolean,
    val voidAllowed: Boolean,
    val focused: Boolean,
)

/** Events explain the relationship; they never calculate a new balance or confer write permission. */
@Composable
internal fun DebtActivityRow(state: DebtActivityRowState, callbacks: DebtActivityCallbacks) {
    val event = state.event
    val bringIntoView = remember { BringIntoViewRequester() }
    LaunchedEffect(state.focused) {
        if (state.focused) {
            withFrameNanos { }
            bringIntoView.bringIntoView()
        }
    }
    AppListRow(showDivider = state.showDivider) {
        Column(modifier = Modifier.fillMaxWidth().bringIntoViewRequester(bringIntoView),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
            Text(stringResource(debtActivityKindLabel(event.kind)), style = MaterialTheme.typography.titleSmall)
            if (state.focused) Text(stringResource(R.string.debt_activity_linked_payment), style = MaterialTheme.typography.labelMedium)
            val actor = if (event.actorIsYou) stringResource(R.string.debt_activity_actor_you)
                else event.actorDisplayName
            Text(listOfNotNull(displayDateTime(event.recordedAt), actor).joinToString(" · "),
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            event.amountCents?.let {
                val amount = formatDisplayAmount(it, CurrencyDisplay.forRecord(state.homeCurrencyCode))
                Text(if (event.kind == "adjustment" && it > 0) "+$amount" else amount, style = MaterialTheme.typography.bodyLarge)
            }
            event.repayment?.let { repayment ->
                DebtActivityRepayment(repayment, state.homeCurrencyCode, state.voidAllowed,
                    onVoid = { callbacks.onVoidRepayment(repayment) })
            }
            if (event.repayment?.voidFact?.reason != event.reason) event.reason?.let {
                Text(it, style = MaterialTheme.typography.bodyMedium)
            }
            event.proposal?.let { proposal ->
                DebtActivityProposal(proposal, resolved = event.kind == "proposal_resolved", callbacks.onOpenRepayment)
            }
        }
    }
}

@Composable
private fun DebtActivityProposal(proposal: MemberRepaymentProposal, resolved: Boolean, openRepayment: (String) -> Unit) {
    val display = CurrencyDisplay.forRecord(proposal.homeCurrencyCode)
    Text(stringResource(R.string.debt_activity_proposed_amount, formatDisplayAmount(proposal.proposedAmountCents, display)))
    Text(stringResource(R.string.debt_activity_paid_at, displayDate(proposal.paidAt)), style = MaterialTheme.typography.bodySmall)
    if (resolved) {
        Text(stringResource(memberProposalStatusLabel(proposal.status)), style = MaterialTheme.typography.labelMedium)
        proposal.confirmedAmountCents?.let {
            Text(stringResource(R.string.debt_activity_confirmed_amount, formatDisplayAmount(it, display)))
        }
        proposal.committedRepaymentPublicId?.let { repaymentId ->
            QuietOutlinedButton(text = stringResource(R.string.debt_activity_open_repayment), onClick = { openRepayment(repaymentId) })
        }
    } else {
        Text(stringResource(R.string.debt_activity_proposal_expires, displayDateTime(proposal.expiresAt)),
            style = MaterialTheme.typography.bodySmall)
    }
    val original = proposal.originalAmountMinor
    proposal.originalCurrencyCode?.takeIf { original != null && it != proposal.homeCurrencyCode }?.let { code ->
        Text(stringResource(R.string.debt_repayment_original_amount,
            formatDisplayAmount(requireNotNull(original), CurrencyDisplay.forRecord(code))), style = MaterialTheme.typography.bodySmall)
    }
    proposal.note?.takeIf { it.isNotBlank() }?.let { Text(it, style = MaterialTheme.typography.bodyMedium) }
    proposal.supersedesProposalPublicId?.let {
        Text(stringResource(R.string.debt_activity_supersedes), style = MaterialTheme.typography.bodySmall)
    }
}

@StringRes
internal fun debtActivityKindLabel(kind: String): Int = when (kind) {
    "created" -> R.string.debt_activity_created
    "repayment" -> R.string.debt_activity_repayment
    "repayment_void" -> R.string.debt_activity_repayment_void
    "adjustment" -> R.string.debt_activity_adjustment
    "forgiveness" -> R.string.debt_activity_forgiveness
    "debt_void" -> R.string.debt_activity_debt_void
    "proposal_created" -> R.string.debt_activity_proposal_created
    "proposal_resolved" -> R.string.debt_activity_proposal_resolved
    else -> R.string.debt_activity_unknown
}

@StringRes
private fun memberProposalStatusLabel(status: String): Int = when (status) {
    MemberProposalStatuses.PENDING -> R.string.debt_proposal_status_pending
    MemberProposalStatuses.CONFIRMED -> R.string.debt_proposal_status_confirmed
    MemberProposalStatuses.PARTIALLY_CONFIRMED -> R.string.debt_proposal_status_partially_confirmed
    MemberProposalStatuses.REJECTED -> R.string.debt_proposal_status_rejected
    MemberProposalStatuses.WITHDRAWN -> R.string.debt_proposal_status_withdrawn
    MemberProposalStatuses.EXPIRED -> R.string.debt_proposal_status_expired
    MemberProposalStatuses.SUPERSEDED -> R.string.debt_proposal_status_superseded
    else -> R.string.debt_activity_unknown
}

/** Built-in provenance gets its meaning; a user-authored source remains its original text. */
@StringRes
internal fun debtActivityFxSourceLabel(source: String): Int? = when (source) {
    FxContract.SourceManual -> R.string.debt_activity_fx_manual
    FxContract.SourceBase -> R.string.debt_activity_fx_base
    "imported" -> R.string.debt_activity_fx_imported
    "ecb" -> R.string.debt_activity_fx_ecb
    else -> null
}
