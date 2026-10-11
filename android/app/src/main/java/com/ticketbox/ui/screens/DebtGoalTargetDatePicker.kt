package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.CalendarToday
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDefaults
import androidx.compose.material3.DisplayMode
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.Surface
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.ticketbox.R
import com.ticketbox.ui.components.AppFormFieldGroup
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.ui.components.AppOutlinedButtonOptions
import com.ticketbox.ui.components.AppAction
import com.ticketbox.ui.components.AppActionRow
import com.ticketbox.ui.design.AppAdaptiveBreakpoints
import com.ticketbox.ui.design.AppSpacing
import java.time.Instant
import java.time.ZoneOffset

/** Picking or clearing edits the retained draft. Only the task's Save admits a command. */
@Composable
internal fun DebtGoalDateField(value: String?, enabled: Boolean, onChange: (String?) -> Unit) {
    var showPicker by rememberSaveable { mutableStateOf(false) }
    AppFormFieldGroup(label = stringResource(R.string.debt_goal_date_label)) {
        AppOutlinedButton(onClick = { showPicker = true }, modifier = Modifier.fillMaxWidth(),
            options = AppOutlinedButtonOptions(enabled = enabled)) {
            Text(value ?: stringResource(R.string.debt_goal_date_empty), modifier = Modifier.weight(1f))
            Icon(Icons.Outlined.CalendarToday, contentDescription = stringResource(R.string.debt_goal_target_date_picker_title))
        }
        if (value != null) TextButton(enabled = enabled, onClick = { onChange(null) }) {
            Text(stringResource(R.string.debt_goal_target_date_clear))
        }
    }
    if (showPicker && enabled) DebtTargetDatePickerDialog(value, onSelect = {
        onChange(it)
        showPicker = false
    }, onDismiss = { showPicker = false })
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DebtTargetDatePickerDialog(value: String?, onSelect: (String) -> Unit, onDismiss: () -> Unit) {
    Dialog(onDismissRequest = onDismiss, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(modifier = Modifier.padding(AppSpacing.compactGap)
            .widthIn(max = AppAdaptiveBreakpoints.focusContentMaxWidth).fillMaxWidth(),
            shape = DatePickerDefaults.shape, color = DatePickerDefaults.colors().containerColor) {
            BoxWithConstraints {
                // A calendar needs seven accessible day targets; use the same date input when they cannot fit.
                val calendarFits = maxWidth / LocalDensity.current.fontScale.coerceAtLeast(1f) >=
                    AppSpacing.controlMinHeight * 7 + AppSpacing.cardPaddingSmall * 2
                val picker = rememberDatePickerState(initialSelectedDateMillis = value?.let(::isoDateToEpochMillis),
                    initialDisplayMode = if (calendarFits) DisplayMode.Picker else DisplayMode.Input)
                LaunchedEffect(calendarFits) { if (!calendarFits) picker.displayMode = DisplayMode.Input }
                Column {
                    DatePicker(state = picker, modifier = Modifier.weight(1f, fill = false)
                        .verticalScroll(rememberScrollState()), headline = null,
                        showModeToggle = calendarFits, focusRequester = null, title = {
                            Text(stringResource(R.string.debt_goal_target_date_picker_title),
                                style = MaterialTheme.typography.titleLarge, modifier = Modifier.padding(AppSpacing.cardPadding))
                        })
                    AppActionRow(modifier = Modifier.padding(AppSpacing.cardPadding),
                        primary = AppAction(stringResource(R.string.common_confirm), enabled = picker.selectedDateMillis != null,
                            onClick = { picker.selectedDateMillis?.let {
                                onSelect(Instant.ofEpochMilli(it).atZone(ZoneOffset.UTC).toLocalDate().toString())
                            } }),
                        secondary = AppAction(stringResource(R.string.common_cancel), onClick = onDismiss))
                }
            }
        }
    }
}
