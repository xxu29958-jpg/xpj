package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.text.TextAutoSize
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.sp
import com.ticketbox.ui.components.AppSectionHeader
import com.ticketbox.ui.components.displayDateTime
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

internal data class ExpenseDateControlState(
    val title: String,
    val expenseTime: String,
    val enabled: Boolean = true,
    val showClear: Boolean = false,
)

internal data class ExpenseDateControlLabels(
    val pickDate: String,
    val pickTime: String,
    val useNow: String,
    val clear: String? = null,
)

internal data class ExpenseDateControlActions(
    val onPickDate: () -> Unit,
    val onPickTime: () -> Unit,
    val onUseNow: () -> Unit,
    val onClear: (() -> Unit)? = null,
)

@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun ExpenseDateControl(
    state: ExpenseDateControlState,
    labels: ExpenseDateControlLabels,
    actions: ExpenseDateControlActions,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        AppSectionHeader(title = state.title)
        Text(
            text = displayDateTime(state.expenseTime),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodyMedium,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
        FlowRow(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        ) {
            ExpenseDateControlAction(
                text = labels.pickDate,
                enabled = state.enabled,
                onClick = actions.onPickDate,
            )
            ExpenseDateControlAction(
                text = labels.pickTime,
                enabled = state.enabled,
                onClick = actions.onPickTime,
            )
            ExpenseDateControlAction(
                text = labels.useNow,
                enabled = state.enabled,
                onClick = actions.onUseNow,
            )
            if (state.showClear && labels.clear != null && actions.onClear != null) {
                ExpenseDateControlAction(
                    text = labels.clear,
                    enabled = state.enabled,
                    onClick = actions.onClear,
                )
            }
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.soft))
    }
}

@Composable
private fun ExpenseDateControlAction(
    text: String,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    TextButton(
        modifier = Modifier
            .heightIn(min = AppSpacing.controlMinHeight)
            .widthIn(min = AppSpacing.controlMinHeight),
        enabled = enabled,
        contentPadding = PaddingValues(horizontal = AppSpacing.smallGap, vertical = AppSpacing.tinyGap),
        onClick = onClick,
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.labelLarge,
            fontWeight = AppTextHierarchy.heading.weight,
            maxLines = 1,
            softWrap = false,
            overflow = TextOverflow.Clip,
            autoSize = TextAutoSize.StepBased(minFontSize = 12.sp, maxFontSize = 14.sp, stepSize = 1.sp),
        )
    }
}
