package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.MonthCalendarFixture
import com.ticketbox.data.repository.calendar
import com.ticketbox.domain.model.StreamOffsetKind
import java.time.Clock
import java.time.Instant
import java.time.ZoneId
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.cancel
import kotlinx.coroutines.test.advanceUntilIdle
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse

@OptIn(ExperimentalCoroutinesApi::class)
internal class ExpenseOffsetCalendarTest : ExpenseFactViewModelTestBase() {
    private val clock = Clock.fixed(Instant.parse("2026-04-30T16:30:00Z"), ZoneId.of("Asia/Shanghai"))

    @Test fun newRefundUsesLedgerDayAcrossTheDeviceMonthBoundary() = edit { fake ->
        val calendars = MonthCalendarFixture(fake.correctionBinding,
            calendar(fake.correctionBinding, "America/Los_Angeles"))
        val vm = ExpenseFactViewModel(7L, fake, calendars = calendars, clock = clock)
        try {
            advanceUntilIdle()
            vm.openOffsetSheet(StreamOffsetKind.Refund)
            advanceUntilIdle()
            assertEquals("2026-04-30", vm.uiState.value.offsetForm.accountingDate,
                "A new refund belongs to the ledger's current day, not the device's next month")
        } finally {
            vm.viewModelScope.cancel()
        }
    }

    @Test fun reopeningOriginalDoesNotAdoptALaterCalendarOrClock() = edit { fake ->
        val calendars = MonthCalendarFixture(fake.correctionBinding, calendar(fake.correctionBinding))
        val first = ExpenseFactViewModel(7L, fake, calendars = calendars, clock = clock)
        advanceUntilIdle()
        first.openOffsetSheet(StreamOffsetKind.Refund)
        first.updateOffsetFormField(OffsetFormField.AccountingDate, "2025-12-31")
        first.closeOffsetSheet()
        advanceUntilIdle()
        first.viewModelScope.cancel()
        calendars.rule = calendar(fake.correctionBinding, "Asia/Tokyo")
        val later = Clock.fixed(Instant.parse("2027-01-01T01:00:00Z"), clock.zone)
        val reopened = ExpenseFactViewModel(7L, fake, calendars = calendars, clock = later)
        try {
            advanceUntilIdle()
            reopened.openOffsetSheet(StreamOffsetKind.Refund)
            advanceUntilIdle()
            assertEquals("2025-12-31", reopened.uiState.value.offsetForm.accountingDate)
        } finally {
            reopened.viewModelScope.cancel()
        }
    }

    @Test fun unresolvedCalendarAllowsExplicitDateAndLateReadCannotReplaceIt() = edit { fake ->
        val gate = CompletableDeferred<Unit>()
        val calendars = MonthCalendarFixture(fake.correctionBinding).apply {
            this.gate = { gate.await() }
            response = Result.success(calendar(binding))
        }
        val vm = ExpenseFactViewModel(7L, fake, calendars = calendars, clock = clock)
        try {
            advanceUntilIdle()
            vm.openOffsetSheet(StreamOffsetKind.Refund)
            assertEquals("", vm.uiState.value.offsetForm.accountingDate)
            vm.updateOffsetFormField(OffsetFormField.AccountingDate, "2026-02-03")
            vm.updateOffsetFormField(OffsetFormField.Amount, "3.00")
            vm.updateOffsetFormField(OffsetFormField.Reason, "Recorded day")
            advanceUntilIdle()
            vm.submitOffset()
            advanceUntilIdle()
            assertEquals("2026-02-03", fake.lastOffsetDraft?.accountingDate)
            gate.complete(Unit)
            advanceUntilIdle()
            assertEquals(1, fake.createOffsetCalls)
            assertEquals("2026-02-03", fake.lastOffsetDraft?.accountingDate)
        } finally {
            vm.viewModelScope.cancel()
        }
    }

    @Test fun lateCalendarCannotEnterReplacementBinding() = edit { fake ->
        val gate = CompletableDeferred<Unit>()
        val calendars = MonthCalendarFixture(fake.correctionBinding).apply {
            this.gate = { gate.await() }
            response = Result.success(calendar(binding))
        }
        val vm = ExpenseFactViewModel(7L, fake, calendars = calendars, clock = clock)
        try {
            advanceUntilIdle()
            vm.openOffsetSheet(StreamOffsetKind.Refund)
            val access = requireNotNull(fake.correctionObservations.value.access)
            calendars.binding = access.binding.copy(bindingRevision = "replacement")
            fake.correctionObservations.value = fake.correctionObservations.value.copy(
                access = access.copy(binding = calendars.binding))
            advanceUntilIdle()
            gate.complete(Unit)
            advanceUntilIdle()
            assertFalse(vm.uiState.value.offsetForm.open)
            assertEquals("", vm.uiState.value.offsetForm.accountingDate)
        } finally {
            vm.viewModelScope.cancel()
        }
    }
}
