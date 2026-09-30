package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.RepaymentDraft
import com.ticketbox.domain.model.RepaymentDraftStatuses
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppDataAuthorityStrip
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.DataAuthorityTone
import com.ticketbox.ui.components.displayDateTime
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.RepaymentDraftInboxUiState

@Composable
internal fun RepaymentDraftReadHeader(state: RepaymentDraftInboxUiState, history: Boolean, onHistory: (Boolean) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        state.capturesFetchedAt?.let { time ->
            AppDataAuthorityStrip(
                title = stringResource(if (state.capturesFromCache) R.string.repayment_draft_read_cached else R.string.repayment_draft_read_current),
                body = stringResource(R.string.repayment_draft_read_time, displayDateTime(time)),
                tone = if (state.capturesFromCache) DataAuthorityTone.LocalCache else DataAuthorityTone.Backend,
            )
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            FilterChip(!history, { onHistory(false) }, label = {
                Text(stringResource(R.string.repayment_draft_pending_count, state.drafts.count { it.isPending }))
            })
            FilterChip(history, { onHistory(true) }, label = {
                Text(stringResource(R.string.repayment_draft_history_count, state.drafts.count { !it.isPending }))
            })
        }
        if (!state.isLoading && state.capturesFetchedAt != null && state.focusedDraftPublicId != null &&
            state.drafts.none { it.publicId == state.focusedDraftPublicId }) {
            AppStatusBanner(UiText.res(if (state.capturesFromCache) R.string.repayment_draft_original_missing_cache
                else R.string.repayment_draft_original_unavailable), MessageTone.Info)
        }
    }
}

@Composable
internal fun RepaymentDraftResolved(draft: RepaymentDraft, onOpenDebt: () -> Unit) {
    val status = when (draft.status) {
        RepaymentDraftStatuses.CONFIRMED -> R.string.repayment_draft_recorded
        RepaymentDraftStatuses.DISMISSED -> R.string.repayment_draft_ignored
        else -> R.string.repayment_draft_unknown_status
    }
    Text(stringResource(status), style = MaterialTheme.typography.titleSmall)
    draft.resolvedAt?.let { Text(displayDateTime(it), style = MaterialTheme.typography.bodySmall) }
    if (draft.status == RepaymentDraftStatuses.CONFIRMED && draft.committedDebtPublicId != null) {
        TextButton(onClick = onOpenDebt) { Text(stringResource(R.string.repayment_draft_open_record)) }
    }
}
