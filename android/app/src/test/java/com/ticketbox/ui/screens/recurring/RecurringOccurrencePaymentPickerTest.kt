package com.ticketbox.ui.screens.recurring

import com.ticketbox.data.repository.confirmedExpenseDtoFixture
import com.ticketbox.data.repository.toDomain
import com.ticketbox.domain.model.ConfirmedStreamItem
import com.ticketbox.domain.model.ExpenseLineageStatus
import kotlin.test.Test
import kotlin.test.assertEquals

class RecurringOccurrencePaymentPickerTest {
    @Test
    fun acceptedExpenseIdPinsAcrossMonthAndSearchWithoutUsingClientRef() {
        val grocery = payment(id = 41, merchant = "grocery", streamDate = "2026-09-03", clientRef = "period-ref")
        val subscription = payment(id = 9, merchant = "Subscription", streamDate = "2026-08-05", clientRef = "period-ref")
        assertEquals(
            listOf(41L, 9L),
            occurrencePaymentChoices(
                listOf(grocery, subscription),
                month = "2026-08",
                query = "Subscription",
                preferredExpenseId = 41,
            ).map { it.root.id },
        )
    }

    @Test
    fun matchingClientRefDoesNotInventAPreferredBill() {
        val grocery = payment(id = 41, merchant = "grocery", streamDate = "2026-09-03", clientRef = "period-ref")
        assertEquals(
            emptyList(),
            occurrencePaymentChoices(listOf(grocery), month = "2026-08", query = "Subscription"),
        )
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
