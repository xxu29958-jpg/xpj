package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.repository.FundsInput
import com.ticketbox.ui.components.AppListRow
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.FundsUiState
import com.ticketbox.viewmodel.FundsViewModel
import com.ticketbox.viewmodel.RepaymentDraftInboxUiState
import com.ticketbox.viewmodel.start

@Composable
internal fun RepaymentCaptureFundingEntry(state: RepaymentDraftInboxUiState, onFundCapture: (String) -> Unit) {
    val capture = state.drafts.find { it.publicId == state.reviewId && it.isPending } ?: return
    AppSecondaryButton(stringResource(R.string.funds_capture_open),
        enabled = state.canModify && !state.review.bindingChanged && state.review.input?.submittedAction == null) {
        onFundCapture(capture.publicId)
    }
}

internal fun LazyListScope.captureAccounts(state: FundsUiState, vm: FundsViewModel) {
    val capture = state.repaymentCapture
    item {
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            if (state.task.input != null) AppSecondaryButton(stringResource(R.string.funds_capture_resume), onClick = vm::resume)
            if (capture != null) {
                Text(stringResource(R.string.funds_capture_original,
                    money(capture.originalAmountMinor, capture.originalCurrencyCode), capture.merchantLabel.orEmpty()))
                Text(stringResource(if (capture.isPending) R.string.funds_capture_choose else R.string.funds_capture_resolved))
            } else if (!state.loading) Text(stringResource(R.string.funds_capture_unavailable))
            if (capture?.isPending == true && state.access?.canModify == true) {
                AppSecondaryButton(stringResource(R.string.funds_capture_add)) { vm.start("create") }
            }
        }
    }
    if (capture?.isPending == true && state.access?.canModify == true) {
        items(state.accounts.filter { it.kind == "credit" && !it.archived }, key = { it.publicId }) { account ->
            AppListRow(onClick = { vm.open(account.publicId, forCapture = true) }) {
                Text(account.name + account.tail?.let { " · $it" }.orEmpty())
            }
        }
    }
}

@Composable
internal fun FundsCaptureFields(input: FundsInput, enabled: Boolean, vm: FundsViewModel) {
    if (input.sourceRepaymentDraftId.isBlank()) return
    Text(stringResource(R.string.funds_capture_original, "${input.sourceCurrency} ${input.sourceAmount}", input.sourceLabel))
    Text(stringResource(R.string.funds_capture_basis))
    listOf("payer_total" to R.string.funds_capture_payer_total, "principal" to R.string.funds_capture_principal,
        "corrected" to R.string.funds_capture_corrected).forEach { (basis, label) ->
        FilterChip(selected = input.sourceAmountBasis == basis, enabled = enabled,
            onClick = { vm.edit { it.copy(sourceAmountBasis = basis) } }, label = { Text(stringResource(label)) })
    }
    if (input.sourceAmountBasis == "corrected") FundsField(stringResource(R.string.funds_capture_reason), input.sourceReviewReason, enabled) { value ->
        vm.edit { it.copy(sourceReviewReason = value) }
    }
}
