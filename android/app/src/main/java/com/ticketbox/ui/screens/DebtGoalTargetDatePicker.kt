package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.DebtGoalComposition
import com.ticketbox.domain.model.Goal

/**
 * Payoff target-date picker for pure external-debt repayment goals. Hidden for member/mixed
 * goals even if stale view state tries to reopen it after switching detail panes.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun DebtTargetDatePickerDialog(
    visible: Boolean,
    selected: Goal?,
    onSetTargetDate: (Long?) -> Unit,
    onDismiss: () -> Unit,
) {
    if (!visible || selected?.debtRepayment?.composition != DebtGoalComposition.External) return
    val deadlineIso = selected.debtRepayment.targetDate
    val pickerState = rememberDatePickerState(
        initialSelectedDateMillis = deadlineIso?.let { isoDateToEpochMillis(it) },
    )
    DatePickerDialog(
        onDismissRequest = onDismiss,
        confirmButton = {
            TextButton(
                onClick = { pickerState.selectedDateMillis?.let { onSetTargetDate(it); onDismiss() } },
                enabled = pickerState.selectedDateMillis != null,
            ) { Text(stringResource(R.string.common_confirm)) }
        },
        dismissButton = {
            Row {
                if (deadlineIso != null) {
                    TextButton(onClick = { onSetTargetDate(null); onDismiss() }) {
                        Text(stringResource(R.string.debt_goal_target_date_clear))
                    }
                }
                TextButton(onClick = onDismiss) { Text(stringResource(R.string.common_cancel)) }
            }
        },
    ) {
        DatePicker(
            state = pickerState,
            title = {
                Text(
                    stringResource(R.string.debt_goal_target_date_picker_title),
                    modifier = Modifier.padding(start = 24.dp, end = 12.dp, top = 16.dp),
                )
            },
        )
    }
}
