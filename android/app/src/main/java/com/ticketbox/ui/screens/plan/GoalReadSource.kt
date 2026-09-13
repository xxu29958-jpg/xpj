package com.ticketbox.ui.screens.plan

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.components.AppDataAuthorityStrip
import com.ticketbox.ui.components.DataAuthorityTone
import com.ticketbox.ui.components.displayDateTime

@Composable
fun GoalReadSource(fetchedAt: String?, fromCache: Boolean, isLoading: Boolean = false) {
    if (fetchedAt == null) {
        if (isLoading) AppDataAuthorityStrip(DataAuthorityTone.Refreshing)
        return
    }
    AppDataAuthorityStrip(
        title = stringResource(if (fromCache) R.string.goal_read_cached_title else R.string.goal_read_title),
        body = stringResource(if (fromCache) R.string.goal_read_cached_body else R.string.goal_read_body,
            displayDateTime(fetchedAt)),
        tone = if (fromCache) DataAuthorityTone.LocalCache else DataAuthorityTone.Backend,
        modifier = Modifier.testTag("goal-read-source"),
    )
}
