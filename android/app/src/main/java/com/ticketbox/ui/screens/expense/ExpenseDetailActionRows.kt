package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.design.AppAdaptiveBreakpoints

@Composable
internal fun ExpenseDetailActionButtonRow(
    text: String,
    icon: ImageVector,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    onClick: () -> Unit,
) {
    BoxWithConstraints(modifier = modifier.fillMaxWidth()) {
        val buttonModifier = if (maxWidth < AppAdaptiveBreakpoints.contentActionInlineMinWidth) {
            Modifier.fillMaxWidth()
        } else {
            Modifier.align(Alignment.CenterEnd)
        }
        QuietOutlinedButton(
            text = text,
            leadingIcon = icon,
            modifier = buttonModifier,
            enabled = enabled,
            onClick = onClick,
        )
    }
}
