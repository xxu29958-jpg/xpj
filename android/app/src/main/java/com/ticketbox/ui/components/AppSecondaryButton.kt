package com.ticketbox.ui.components

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector

@Composable
fun AppSecondaryButton(
    text: String,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    leadingIcon: ImageVector? = null,
    onClick: () -> Unit,
) {
    QuietOutlinedButton(
        text = text,
        modifier = modifier,
        enabled = enabled,
        leadingIcon = leadingIcon,
        onClick = onClick,
    )
}
