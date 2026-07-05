package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.Dp
import com.ticketbox.ui.design.AppAdaptiveBreakpoints
import com.ticketbox.ui.design.AppSpacing

internal enum class AppAdaptiveEqualControlMode {
    Stacked,
    Inline,
}

@Composable
fun AppAdaptiveEqualControlRow(
    modifier: Modifier = Modifier,
    verticalAlignment: Alignment.Vertical = Alignment.CenterVertically,
    leading: @Composable (Modifier) -> Unit,
    trailing: @Composable (Modifier) -> Unit,
) {
    BoxWithConstraints(modifier = modifier.fillMaxWidth()) {
        when (resolveAppAdaptiveEqualControlMode(maxWidth)) {
            AppAdaptiveEqualControlMode.Stacked -> Column(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.chipGap),
            ) {
                leading(Modifier.fillMaxWidth())
                trailing(Modifier.fillMaxWidth())
            }
            AppAdaptiveEqualControlMode.Inline -> Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap),
                verticalAlignment = verticalAlignment,
            ) {
                leading(Modifier.weight(1f))
                trailing(Modifier.weight(1f))
            }
        }
    }
}

internal fun resolveAppAdaptiveEqualControlMode(maxWidth: Dp): AppAdaptiveEqualControlMode =
    if (maxWidth < AppAdaptiveBreakpoints.contentActionInlineMinWidth) {
        AppAdaptiveEqualControlMode.Stacked
    } else {
        AppAdaptiveEqualControlMode.Inline
    }
