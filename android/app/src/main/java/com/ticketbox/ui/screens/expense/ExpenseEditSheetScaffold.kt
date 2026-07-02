package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import com.ticketbox.R
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.tabularNum

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
    Column(
        modifier = modifier
            .fillMaxWidth()
            .navigationBarsPadding()
            .padding(
                horizontal = AppSpacing.screenHorizontal,
                vertical = AppSpacing.contentGap,
            ),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        ExpenseEditSheetHeader(title = title, subtitle = subtitle)
        content()
    }
}

@Composable
private fun ExpenseEditSheetHeader(
    title: String,
    subtitle: String,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
        Text(
            text = title,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = AppTextHierarchy.heading.weight,
        )
        Text(
            text = subtitle,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
internal fun ExpenseEditSheetActions(
    state: ExpenseEditSheetActionState,
    handlers: ExpenseEditSheetActionHandlers,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        AppOutlinedButton(
            onClick = handlers.onDismiss,
            enabled = !state.saving,
            modifier = Modifier.weight(1f),
        ) {
            Text(stringResource(R.string.common_cancel))
        }
        Button(
            onClick = handlers.onSubmit,
            enabled = state.primaryEnabled && !state.saving,
            modifier = Modifier.weight(1f),
        ) {
            Text(if (state.saving) state.savingText else state.primaryText)
        }
    }
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
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = row.label,
                style = MaterialTheme.typography.bodyMedium,
                color = if (row.emphasis) {
                    MaterialTheme.colorScheme.error
                } else {
                    MaterialTheme.colorScheme.onSurfaceVariant
                },
            )
            row.hint?.let {
                Text(
                    text = it,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = AppAlpha.strong),
                )
            }
        }
        Text(
            text = row.value,
            style = MaterialTheme.typography.bodyMedium.tabularNum(),
            color = if (row.emphasis) {
                MaterialTheme.colorScheme.error
            } else {
                MaterialTheme.colorScheme.onSurface
            },
            fontWeight = if (row.emphasis) FontWeight.SemiBold else AppTextHierarchy.body.weight,
        )
    }
}
