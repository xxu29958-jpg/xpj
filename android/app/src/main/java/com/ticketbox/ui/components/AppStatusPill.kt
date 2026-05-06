package com.ticketbox.ui.components

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier

@Composable
fun AppStatusPill(
    text: String,
    modifier: Modifier = Modifier,
    active: Boolean = true,
) {
    StatusPill(
        text = text,
        modifier = modifier,
        active = active,
    )
}
