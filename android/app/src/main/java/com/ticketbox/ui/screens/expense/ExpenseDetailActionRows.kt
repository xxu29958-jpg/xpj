package com.ticketbox.ui.screens.expense

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import com.ticketbox.ui.components.AppAdaptiveTrailingActionRow
import com.ticketbox.ui.components.QuietOutlinedButton

@Composable
internal fun ExpenseDetailActionButtonRow(
    text: String,
    icon: ImageVector,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    onClick: () -> Unit,
) {
    AppAdaptiveTrailingActionRow(modifier = modifier) { buttonModifier ->
        QuietOutlinedButton(
            text = text,
            leadingIcon = icon,
            modifier = buttonModifier,
            enabled = enabled,
            onClick = onClick,
        )
    }
}
