package com.ticketbox.ui.screens

import androidx.compose.foundation.lazy.LazyListScope
import com.ticketbox.R
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppStatusBanner

internal fun LazyListScope.billSplitBanners(
    message: UiText?,
    showReadOnly: Boolean,
) {
    message?.let {
        item { AppStatusBanner(message = it, tone = MessageTone.Danger) }
    }
    if (showReadOnly) {
        item {
            AppStatusBanner(
                message = UiText.res(R.string.common_readonly_ledger),
                tone = MessageTone.Info,
                announceUpdates = false,
            )
        }
    }
}
