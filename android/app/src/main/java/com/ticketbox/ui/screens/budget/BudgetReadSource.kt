package com.ticketbox.ui.screens.budget

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.components.AppDataAuthorityStrip
import com.ticketbox.ui.components.DataAuthorityTone
import com.ticketbox.ui.components.displayDateTime

@Composable
fun BudgetReadSource(fetchedAt: String?, fromCache: Boolean, isLoading: Boolean = false, prominent: Boolean = false) {
    if (fetchedAt == null) {
        if (isLoading) AppDataAuthorityStrip(DataAuthorityTone.Refreshing)
        return
    }
    if (fromCache && prominent) {
        BudgetCachedReadSource(fetchedAt)
        return
    }
    AppDataAuthorityStrip(
        title = stringResource(if (fromCache) R.string.budget_read_cached_title else R.string.budget_read_title),
        body = stringResource(if (fromCache) R.string.budget_read_cached_body else R.string.budget_read_body,
            displayDateTime(fetchedAt)),
        tone = if (fromCache) DataAuthorityTone.LocalCache else DataAuthorityTone.Backend,
        modifier = Modifier.testTag("budget-read-source"),
    )
}
