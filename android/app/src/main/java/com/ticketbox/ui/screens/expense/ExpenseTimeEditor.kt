package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.TimeInput
import androidx.compose.material3.rememberTimePickerState
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.remote.dto.LedgerCalendarDto
import com.ticketbox.data.repository.LedgerCalendarRepository
import com.ticketbox.domain.model.ExpenseAccountingTime
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.design.AppSpacing
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.ZoneOffset

val LocalLedgerCalendarRepository = staticCompositionLocalOf<LedgerCalendarRepository?> { null }
internal const val TAG_TIME_ROW = "expense-edit-time-row"

@Composable
internal fun rememberLedgerCalendar(revision: Long? = null): CalendarRuleLoading {
    val repository = LocalLedgerCalendarRepository.current
    val binding = repository?.currentBinding()
    var rule by remember(repository, binding, revision) { mutableStateOf(binding?.let { repository.cached(it, revision) }) }
    var attempt by remember { mutableStateOf(0) }
    LaunchedEffect(repository, binding, revision, attempt) {
        if (binding != null) repository.refresh(binding, revision).onSuccess { if (it != null) rule = it }
    }
    return CalendarRuleLoading(rule) { attempt++ }
}

internal data class CalendarRuleLoading(val rule: LedgerCalendarDto?, val retry: () -> Unit)

@Composable
internal fun rememberExpenseTimeForm(
    key: Any,
    instant: String?,
    evidence: ExpenseAccountingTime? = null,
    saved: String? = null,
): Pair<ExpenseTimeForm, (ExpenseTimeForm) -> Unit> {
    val rule = rememberLedgerCalendar(evidence?.calendarRevision).rule
    var json by rememberSaveable(key) {
        mutableStateOf(saved ?: ExpenseTimeForm.initial(instant, evidence, rule, ZoneId.systemDefault()).toSavedJson())
    }
    return requireNotNull(readExpenseTimeForm(json)) to { json = it.toSavedJson() }
}

/** One raw date/precision/zone editor for manual, pending, recurring payment and explicit correction. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun ExpenseTimeEditor(form: ExpenseTimeForm, onChange: (ExpenseTimeForm) -> Unit, enabled: Boolean) {
    val loading = rememberLedgerCalendar(form.calendarRevision)
    val rule = loading.rule
    var pickingDate by rememberSaveable { mutableStateOf(false) }
    var pickingTime by rememberSaveable { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
        Text(stringResource(R.string.calendar_input_title), style = MaterialTheme.typography.titleSmall)
        FlowRow(horizontalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
            FilterChip(selected = form.precision == "instant", onClick = { onChange(form.withPrecision("instant", rule)) },
                label = { Text(stringResource(R.string.calendar_input_instant)) }, enabled = enabled)
            FilterChip(selected = form.precision == "date_only", onClick = { onChange(form.withPrecision("date_only", rule)) },
                label = { Text(stringResource(R.string.calendar_input_date_only)) }, enabled = enabled)
            TextButton(onClick = { pickingDate = true }, enabled = enabled, modifier = Modifier.testTag(TAG_TIME_ROW)) { Text(stringResource(R.string.expense_edit_date_pick_date_button)) }
            if (form.precision == "instant") TextButton(onClick = { pickingTime = true }, enabled = enabled) { Text(stringResource(R.string.expense_edit_date_pick_time_button)) }
            TextButton(onClick = {
                val now = Instant.now().atZone(ZoneId.of(form.sourceZone))
                onChange(form.copy(precision = "instant", date = now.toLocalDate().toString(), time = now.toLocalTime().toString(),
                    offsetSeconds = now.offset.totalSeconds, changed = true))
            }, enabled = enabled && runCatching { ZoneId.of(form.sourceZone) }.isSuccess) { Text(stringResource(R.string.expense_edit_date_use_now_button)) }
        }
        TimeTextField(stringResource(R.string.calendar_input_day), form.date, enabled) { onChange(form.copy(date = it, offsetSeconds = null, changed = true)) }
        if (form.precision == "instant") {
            TimeTextField(stringResource(R.string.calendar_input_clock), form.time, enabled) { onChange(form.copy(time = it, offsetSeconds = null, changed = true)) }
            TimeTextField(stringResource(R.string.calendar_input_zone), form.sourceZone, enabled) { onChange(form.copy(sourceZone = it, offsetSeconds = null, changed = true)) }
            val offsets = form.validOffsets()
            if (offsets.size > 1) FlowRow(horizontalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
                offsets.forEach { offset ->
                    FilterChip(selected = form.offsetSeconds == offset.totalSeconds,
                        onClick = { onChange(form.copy(offsetSeconds = offset.totalSeconds, changed = true)) },
                        label = { Text("UTC$offset") }, enabled = enabled)
                }
            }
        }
        ExpenseCalendarRuleNotice(form, loading, enabled, onChange)
        if (form.changed) form.resolve().error?.let { Text(stringResource(it), color = MaterialTheme.colorScheme.error) }
    }
    if (pickingDate) ExpenseTimeDatePicker(form.date, { onChange(form.copy(date = it, offsetSeconds = null, changed = true)) }) {
        pickingDate = false
    }
    if (pickingTime) ExpenseTimeClockPicker(form.time, { onChange(form.copy(time = it, offsetSeconds = null, changed = true)) }) {
        pickingTime = false
    }
}

@Composable
private fun TimeTextField(label: String, value: String, enabled: Boolean, onChange: (String) -> Unit) {
    AppTextInput(AppTextInputState(label = label, value = value, enabled = enabled), AppTextInputActions(onValueChange = onChange))
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ExpenseTimeDatePicker(date: String, onDate: (String) -> Unit, dismiss: () -> Unit) {
    val selected = runCatching { LocalDate.parse(date).atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli() }.getOrNull()
    val state = rememberDatePickerState(initialSelectedDateMillis = selected)
    DatePickerDialog(onDismissRequest = dismiss, confirmButton = {
        TextButton(onClick = {
            state.selectedDateMillis?.let { onDate(Instant.ofEpochMilli(it).atZone(ZoneOffset.UTC).toLocalDate().toString()) }
            dismiss()
        }) { Text(stringResource(R.string.common_confirm)) }
    }, dismissButton = { TextButton(onClick = dismiss) { Text(stringResource(R.string.common_cancel)) } }) { DatePicker(state, title = { Text(stringResource(R.string.expense_edit_date_picker_title)) }) }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ExpenseTimeClockPicker(time: String, onTime: (String) -> Unit, dismiss: () -> Unit) {
    val parsed = runCatching { java.time.LocalTime.parse(time) }.getOrNull()
    val state = rememberTimePickerState(initialHour = parsed?.hour ?: 0, initialMinute = parsed?.minute ?: 0, is24Hour = true)
    AlertDialog(onDismissRequest = dismiss, title = { Text(stringResource(R.string.expense_edit_time_picker_title)) }, text = { TimeInput(state) }, confirmButton = {
        TextButton(onClick = { onTime(java.time.LocalTime.of(state.hour, state.minute).toString()); dismiss() }) { Text(stringResource(R.string.common_confirm)) }
    }, dismissButton = { TextButton(onClick = dismiss) { Text(stringResource(R.string.common_cancel)) } })
}

@Composable
private fun ExpenseCalendarRuleNotice(
    form: ExpenseTimeForm,
    loading: CalendarRuleLoading,
    enabled: Boolean,
    onChange: (ExpenseTimeForm) -> Unit,
) {
    val rule = loading.rule
    val ruleLabel = form.calendarZone ?: rule?.timezoneName
    Text(if (form.calendarRevision == null) stringResource(R.string.calendar_input_no_rule) else stringResource(R.string.calendar_input_rule, ruleLabel.orEmpty(), form.calendarRevision),
        style = MaterialTheme.typography.bodySmall)
    if (rule == null) TextButton(enabled = enabled, onClick = loading.retry) { Text(stringResource(R.string.calendar_input_retry)) }
    if (form.calendarRevision == null && rule != null) TextButton(enabled = enabled, onClick = {
        onChange(form.copy(calendarRevision = rule.revision, calendarZone = rule.timezoneName, changed = true))
    }) { Text(stringResource(R.string.calendar_input_adopt_rule)) }
}
