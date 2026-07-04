package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import com.ticketbox.ui.design.AppAdaptiveBreakpoints
import com.ticketbox.ui.design.AppSpacing

@Composable
fun AppAdaptiveContentActionRow(
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
    action: @Composable (Modifier) -> Unit,
) {
    BoxWithConstraints(modifier = modifier.fillMaxWidth()) {
        if (maxWidth < AppAdaptiveBreakpoints.contentActionInlineMinWidth) {
            Column(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
            ) {
                content()
                action(Modifier.fillMaxWidth())
            }
        } else {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(modifier = Modifier.weight(1f)) {
                    content()
                }
                action(Modifier)
            }
        }
    }
}

@Composable
fun AppAdaptiveTrailingActionRow(
    modifier: Modifier = Modifier,
    action: @Composable (Modifier) -> Unit,
) {
    BoxWithConstraints(modifier = modifier.fillMaxWidth()) {
        val actionModifier = if (maxWidth < AppAdaptiveBreakpoints.contentActionInlineMinWidth) {
            Modifier.fillMaxWidth()
        } else {
            Modifier.align(Alignment.CenterEnd)
        }
        action(actionModifier)
    }
}
