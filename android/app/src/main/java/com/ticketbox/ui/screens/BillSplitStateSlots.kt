package com.ticketbox.ui.screens

import androidx.compose.runtime.Composable
import com.ticketbox.ui.components.AppContentStateCopy
import com.ticketbox.ui.components.AppContentStatePresentation
import com.ticketbox.ui.components.AppContentStateSlot
import com.ticketbox.ui.components.AppContentStateSpec

@Composable
internal fun BillSplitLoadingState(
    title: String,
    body: String,
    emptyText: String,
) {
    AppContentStateSlot(
        state = AppContentStateSpec(
            loading = true,
            hasData = false,
            copy = AppContentStateCopy(
                loadingTitle = title,
                loadingBody = body,
                emptyText = emptyText,
            ),
            presentation = AppContentStatePresentation.Card,
        ),
    )
}
