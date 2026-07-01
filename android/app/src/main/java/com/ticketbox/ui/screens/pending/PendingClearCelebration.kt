package com.ticketbox.ui.screens.pending

import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.components.ClearCelebration

@Composable
internal fun PendingClearCelebration(visible: Boolean) {
    ClearCelebration(
        visible = visible,
        title = stringResource(R.string.pending_celebration_title),
        body = stringResource(R.string.pending_celebration_body),
        checkDescription = stringResource(R.string.pending_celebration_check_desc),
    )
}
