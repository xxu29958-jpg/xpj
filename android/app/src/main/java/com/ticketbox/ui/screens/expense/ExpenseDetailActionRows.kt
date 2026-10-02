package com.ticketbox.ui.screens.expense

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import com.ticketbox.ui.components.AppAdaptiveTrailingActionRow
import com.ticketbox.ui.components.AppSecondaryButton

@Composable
internal fun ExpenseDetailActionButtonRow(
    text: String,
    icon: ImageVector,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    onClick: () -> Unit,
) {
    AppAdaptiveTrailingActionRow(modifier = modifier) { buttonModifier ->
        AppSecondaryButton(
            text = text,
            leadingIcon = icon,
            modifier = buttonModifier,
            enabled = enabled,
            onClick = onClick,
        )
    }
}
