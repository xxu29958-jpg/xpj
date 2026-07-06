package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.components.AppAdaptiveAmountRowDefaults
import com.ticketbox.ui.components.AppAdaptiveAmountRowStyle
import com.ticketbox.ui.components.AppAdaptiveEditAmountRow
import com.ticketbox.ui.components.AppSheetAction
import com.ticketbox.ui.components.AppSheetActionFeedback
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing

@Immutable
internal data class ExpenseEditSheetActionState(
    val saving: Boolean,
    val primaryEnabled: Boolean,
    val savingText: String,
    val primaryText: String,
)

internal data class ExpenseEditSheetActionHandlers(
    val onDismiss: () -> Unit,
    val onSubmit: () -> Unit,
)

@Immutable
internal data class ExpenseEditReconciliationLine(
    val label: String,
    val value: String,
    val emphasis: Boolean = false,
    val hint: String? = null,
)

@Composable
internal fun ExpenseEditSheetScaffold(
    title: String,
    subtitle: String,
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit,
) {
    AppSheetScaffold(
        title = title,
        subtitle = subtitle,
        modifier = modifier,
    ) {
        content()
    }
}

@Composable
internal fun ExpenseEditSheetActions(
    state: ExpenseEditSheetActionState,
    handlers: ExpenseEditSheetActionHandlers,
) {
    AppSheetActionFeedback(
        primary = AppSheetAction(
            text = if (state.saving) state.savingText else state.primaryText,
            enabled = state.primaryEnabled && !state.saving,
            onClick = handlers.onSubmit,
        ),
        secondary = AppSheetAction(
            text = stringResource(R.string.common_cancel),
            enabled = !state.saving,
            onClick = handlers.onDismiss,
        ),
    )
}

@Composable
internal fun ExpenseEditReconciliationRows(rows: List<ExpenseEditReconciliationLine>) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
    ) {
        rows.forEach { row ->
            ExpenseEditReconciliationRow(row)
        }
    }
}

@Composable
private fun ExpenseEditReconciliationRow(row: ExpenseEditReconciliationLine) {
    val contentColor = if (row.emphasis) {
        MaterialTheme.colorScheme.error
    } else {
        MaterialTheme.colorScheme.onSurfaceVariant
    }
    AppAdaptiveEditAmountRow(
        amount = row.value,
        style = AppAdaptiveAmountRowStyle(
            amountColor = if (row.emphasis) {
                MaterialTheme.colorScheme.error
            } else {
                MaterialTheme.colorScheme.onSurface
            },
            trailingWeight = AppAdaptiveAmountRowDefaults.reconciliationTrailingWeight,
        ),
    ) {
        Column(modifier = Modifier.fillMaxWidth()) {
            Text(
                text = row.label,
                style = MaterialTheme.typography.bodyMedium,
                color = contentColor,
            )
            row.hint?.let {
                Text(
                    text = it,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = AppAlpha.strong),
                )
            }
        }
    }
}
