package com.ticketbox.ui.screens.pending.sheets

import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.ticketbox.ui.components.AppSheetScaffold

@Composable
internal fun ReviewSheetScaffold(
    title: String,
    subtitle: String = "",
    modifier: Modifier = Modifier,
    chrome: ReviewSheetChrome? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    AppSheetScaffold(
        title = title,
        subtitle = subtitle,
        modifier = modifier,
    ) {
        chrome?.let { ReviewQueueHeader(chrome = it) }
        content()
    }
}
