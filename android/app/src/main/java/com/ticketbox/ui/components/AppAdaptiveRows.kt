package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppAdaptiveBreakpoints
import com.ticketbox.ui.design.AppSpacing

private const val ADAPTIVE_AMOUNT_ROW_TRAILING_WEIGHT = 0.44f

@Composable
fun AppAdaptiveContentActionRow(
    modifier: Modifier = Modifier,
    wideActionWeight: Float? = null,
    verticalAlignment: Alignment.Vertical = Alignment.CenterVertically,
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
                verticalAlignment = verticalAlignment,
            ) {
                Box(modifier = Modifier.weight(1f)) {
                    content()
                }
                action(wideActionWeight?.let { Modifier.weight(it) } ?: Modifier)
            }
        }
    }
}

@Composable
fun AppAdaptiveEditAmountRow(
    amount: String,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    BoxWithConstraints(modifier = modifier.fillMaxWidth()) {
        if (maxWidth < AppAdaptiveBreakpoints.editActionInlineMinWidth) {
            Column(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
            ) {
                content()
                AppEndAlignedAmountText(
                    modifier = Modifier.fillMaxWidth(),
                    text = amount,
                    role = AppAmountRole.Compact,
                    color = MaterialTheme.colorScheme.onSurface,
                )
            }
        } else {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
                verticalAlignment = Alignment.Top,
            ) {
                Box(modifier = Modifier.weight(1f)) {
                    content()
                }
                AppEndAlignedAmountText(
                    modifier = Modifier.weight(ADAPTIVE_AMOUNT_ROW_TRAILING_WEIGHT),
                    text = amount,
                    role = AppAmountRole.Compact,
                    color = MaterialTheme.colorScheme.onSurface,
                )
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
