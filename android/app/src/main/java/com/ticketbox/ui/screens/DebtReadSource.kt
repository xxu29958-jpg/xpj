package com.ticketbox.ui.screens

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.components.AppDataAuthorityStrip
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.DataAuthorityTone
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.displayDateTime
import com.ticketbox.viewmodel.DebtDetailUiState

@Composable
internal fun DebtReadSource(fetchedAt: String?, fromCache: Boolean, isLoading: Boolean = false) {
    if (fetchedAt == null) {
        if (isLoading) AppDataAuthorityStrip(DataAuthorityTone.Refreshing)
        return
    }
    AppDataAuthorityStrip(
        title = stringResource(if (fromCache) R.string.debt_read_cached_title else R.string.debt_read_title),
        body = stringResource(if (fromCache) R.string.debt_read_cached_body else R.string.debt_read_body,
            displayDateTime(fetchedAt)),
        tone = if (fromCache) DataAuthorityTone.LocalCache else DataAuthorityTone.Backend,
        modifier = Modifier.testTag("debt-read-source"),
    )
}

@Composable
internal fun DebtActionReadFeedback(state: DebtDetailUiState, onRetry: () -> Unit) {
    state.error?.let { error ->
        AppStatusBanner(message = error, tone = MessageTone.Danger)
        QuietOutlinedButton(text = stringResource(R.string.common_retry), onClick = onRetry,
            enabled = !state.isLoading && !state.isSubmitting)
    }
}
