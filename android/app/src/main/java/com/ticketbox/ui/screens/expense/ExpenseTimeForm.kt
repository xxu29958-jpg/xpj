package com.ticketbox.ui.screens.expense

import com.ticketbox.R
import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.ticketbox.data.remote.dto.LedgerCalendarDto
import com.ticketbox.domain.model.ExpenseAccountingTime
import com.ticketbox.domain.model.ExpenseTimeInput
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.ZoneId
import java.time.ZoneOffset

/** Raw form intent is saved even when a date is invalid or a DST choice remains unresolved. */
@JsonClass(generateAdapter = true)
data class ExpenseTimeForm(
    val precision: String,
    val date: String,
    val time: String,
    val sourceZone: String,
    val offsetSeconds: Int?,
    val originalInstant: String?,
    val calendarRevision: Long?,
    val calendarZone: String?,
    val changed: Boolean = false,
) {
    fun validOffsets(): List<ZoneOffset> = runCatching {
        ZoneId.of(sourceZone).rules.getValidOffsets(LocalDateTime.of(LocalDate.parse(date), LocalTime.parse(time)))
    }.getOrDefault(emptyList())

    fun resolve(): ExpenseTimeResolution {
        val day = runCatching { LocalDate.parse(date) }.getOrNull()
            ?: return ExpenseTimeResolution(error = R.string.calendar_input_invalid_day)
        if (precision == "date_only") {
            val revision = calendarRevision ?: return ExpenseTimeResolution(error = R.string.calendar_input_rule_required)
            return ExpenseTimeResolution(input = ExpenseTimeInput("date_only", revision, day.toString(),
                sourceTimezone = calendarZone, accountingDate = day.toString()))
        }
        val local = runCatching { LocalDateTime.of(day, LocalTime.parse(time)) }.getOrNull()
            ?: return ExpenseTimeResolution(error = R.string.calendar_input_invalid_clock)
        val zone = runCatching { ZoneId.of(sourceZone) }.getOrNull()
            ?: return ExpenseTimeResolution(error = R.string.calendar_input_invalid_zone)
        val offsets = zone.rules.getValidOffsets(local)
        if (offsets.isEmpty()) return ExpenseTimeResolution(error = R.string.calendar_input_gap)
        val offset = offsets.singleOrNull() ?: offsets.find { it.totalSeconds == offsetSeconds }
            ?: return ExpenseTimeResolution(error = R.string.calendar_input_fold)
        val instant = if (!changed && originalInstant != null) originalInstant else local.toInstant(offset).toString()
        val input = calendarRevision?.let { revision ->
            ExpenseTimeInput("instant", revision, day.toString(), instant, sourceZone, offset.totalSeconds)
        }
        return ExpenseTimeResolution(instant, input)
    }

    fun withPrecision(value: String, rule: LedgerCalendarDto?): ExpenseTimeForm = copy(
        precision = value, changed = true,
        calendarRevision = calendarRevision ?: rule?.revision,
        calendarZone = calendarZone ?: rule?.timezoneName,
    )

    companion object {
        fun initial(instant: String?, evidence: ExpenseAccountingTime?, rule: LedgerCalendarDto?, zone: ZoneId): ExpenseTimeForm {
            val source = evidence?.sourceTimezone?.let(ZoneId::of) ?: zone
            val known = evidence?.instantUtc ?: instant
            val local = known?.let { runCatching { Instant.parse(it).atZone(source) }.getOrNull() }
            return ExpenseTimeForm(
                precision = if (evidence?.precision == "date_only") "date_only" else "instant",
                date = evidence?.userLocalDate ?: local?.toLocalDate()?.toString() ?: evidence?.accountingDate.orEmpty(),
                time = local?.toLocalTime()?.toString().orEmpty(), sourceZone = source.id,
                offsetSeconds = evidence?.sourceUtcOffsetSeconds ?: local?.offset?.totalSeconds,
                originalInstant = known, calendarRevision = evidence?.calendarRevision ?: rule?.revision,
                calendarZone = rule?.timezoneName,
            )
        }
    }
}

data class ExpenseTimeResolution(val instant: String? = null, val input: ExpenseTimeInput? = null, val error: Int? = null)

private val timeFormAdapter = Moshi.Builder().build().adapter(ExpenseTimeForm::class.java)
fun ExpenseTimeForm.toSavedJson(): String = timeFormAdapter.toJson(this)
fun readExpenseTimeForm(json: String?): ExpenseTimeForm? = json?.let { runCatching { timeFormAdapter.fromJson(it) }.getOrNull() }
