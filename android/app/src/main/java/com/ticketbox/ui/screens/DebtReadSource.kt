package com.ticketbox.ui.screens

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.components.AppDataAuthorityStrip
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.DataAuthorityTone
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.displayDateTime
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.viewmodel.DebtDetailUiState

@Composable
internal fun DebtReadSource(fetchedAt: String?, fromCache: Boolean, isLoading: Boolean = false,
    testTag: String = "debt-read-source") {
    if (fetchedAt == null) {
        if (isLoading) AppDataAuthorityStrip(DataAuthorityTone.Refreshing)
        return
    }
    AppDataAuthorityStrip(
        title = stringResource(if (fromCache) R.string.debt_read_cached_title else R.string.debt_read_title),
        body = stringResource(if (fromCache) R.string.debt_read_cached_body else R.string.debt_read_body,
            displayDateTime(fetchedAt)),
        tone = if (fromCache) DataAuthorityTone.LocalCache else DataAuthorityTone.Backend,
        modifier = Modifier.testTag(testTag),
    )
}

@Composable
internal fun DebtActionReadFeedback(state: DebtDetailUiState, onRetry: () -> Unit, onReview: () -> Unit) {
    state.error?.let { error ->
        AppStatusBanner(message = error, tone = MessageTone.Danger)
        AppSecondaryButton(text = stringResource(R.string.common_retry), onClick = onRetry,
            enabled = !state.isLoading && !state.isSubmitting)
    }
    if (state.canReviewAction) {
        val latest = requireNotNull(state.debt)
        AppStatusBanner(
            message = com.ticketbox.domain.model.UiText.res(R.string.debt_action_review_latest_body,
                formatDisplayAmount(latest.remainingAmountCents, CurrencyDisplay.forRecord(latest.homeCurrencyCode))),
            tone = MessageTone.Info,
        )
        AppSecondaryButton(text = stringResource(R.string.debt_action_review_latest), onClick = onReview)
    }
}
