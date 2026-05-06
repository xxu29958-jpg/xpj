package com.ticketbox.ui.components

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier

@Composable
fun AppSectionHeader(
    title: String,
    subtitle: String? = null,
    modifier: Modifier = Modifier,
) {
    SectionTitle(
        title = title,
        subtitle = subtitle,
        modifier = modifier,
    )
}
