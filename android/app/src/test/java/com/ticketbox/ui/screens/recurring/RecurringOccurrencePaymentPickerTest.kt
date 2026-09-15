package com.ticketbox.ui.screens.recurring

import com.ticketbox.data.repository.confirmedExpenseDtoFixture
import com.ticketbox.data.repository.toDomain
import com.ticketbox.domain.model.ConfirmedStreamItem
import com.ticketbox.domain.model.ExpenseLineageStatus
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class RecurringOccurrencePaymentPickerTest {
    @Test
    fun unspecifiedOriginDoesNotPreferANullClientRefBill() {
        val grocery = payment(id = 41, merchant = "grocery", streamDate = "2026-09-03", clientRef = null)
        val preferred = preferredOccurrencePaymentId(listOf(grocery), preferredClientRef = null)
        assertNull(preferred)
        assertEquals(
            emptyList(),
            occurrencePaymentChoices(listOf(grocery), month = "2026-08", query = "Subscription", preferredExpenseId = preferred),
        )
    }

    @Test
    fun monthAndSearchMismatchKeepOrdinaryFilterEmptyWithoutPreferredId() {
        val grocery = payment(id = 41, merchant = "grocery", streamDate = "2026-09-03", clientRef = null)
        val subscription = payment(id = 7, merchant = "Subscription", streamDate = "2026-09-01", clientRef = null)
        assertEquals(
            emptyList(),
            occurrencePaymentChoices(listOf(grocery, subscription), month = "2026-08", query = "Subscription"),
        )
    }

    @Test
    fun explicitAcceptedExpenseIdPinsPreferredAheadOfMonthAndSearch() {
        val grocery = payment(id = 41, merchant = "grocery", streamDate = "2026-09-03", clientRef = null)
        val preferred = preferredOccurrencePaymentId(
            listOf(grocery),
            preferredClientRef = null,
            preferredAcceptedExpenseId = 41,
        )
        assertEquals(41L, preferred)
        assertEquals(
            listOf(41L),
            occurrencePaymentChoices(listOf(grocery), month = "2026-08", query = "Subscription", preferredExpenseId = preferred)
                .map { it.root.id },
        )
    }

    @Test
    fun explicitNonBlankClientRefSelectsOnlyThatBill() {
        val grocery = payment(id = 41, merchant = "grocery", streamDate = "2026-09-03", clientRef = null)
        val original = payment(id = 9, merchant = "Subscription", streamDate = "2026-08-05", clientRef = "period-ref")
        assertEquals(9L, preferredOccurrencePaymentId(listOf(grocery, original), "period-ref"))
        assertNull(preferredOccurrencePaymentId(listOf(grocery, original.copy(root = original.root.copy(clientRef = null))), "period-ref"))
    }

    private fun payment(
        id: Long,
        merchant: String,
        streamDate: String,
        clientRef: String?,
    ): ConfirmedStreamItem.ExpenseRow {
        val root = confirmedExpenseDtoFixture().toDomain().copy(
            id = id,
            publicId = "pay-$id",
            merchant = merchant,
            status = "confirmed",
            pendingSync = false,
            clientRef = clientRef,
            amountCents = 1200,
        )
        return ConfirmedStreamItem.ExpenseRow(
            streamDate = streamDate,
            streamAmountCents = 1200,
            root = root,
            lineageStatus = ExpenseLineageStatus.Confirmed,
            lineageHomeNetCents = 1200,
        )
    }
}
