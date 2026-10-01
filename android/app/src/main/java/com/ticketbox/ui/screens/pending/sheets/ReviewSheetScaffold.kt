package com.ticketbox.ui.screens.pending.sheets

import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.runtime.Composable
import com.ticketbox.ui.components.AppSheetScaffold

@Composable
internal fun ReviewSheetScaffold(
    title: String,
    subtitle: String = "",
    chrome: ReviewSheetChrome? = null,
    actions: (@Composable ColumnScope.() -> Unit)? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    AppSheetScaffold(
        title = title,
        subtitle = subtitle,
        actions = actions,
    ) {
        chrome?.let { ReviewQueueHeader(chrome = it) }
        content()
    }
}
