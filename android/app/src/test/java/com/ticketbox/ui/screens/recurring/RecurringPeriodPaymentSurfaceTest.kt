package com.ticketbox.ui.screens.recurring

import com.ticketbox.viewmodel.RecurringOccurrenceUiState
import kotlin.test.Test
import kotlin.test.assertTrue

/** The unpaid period must start a payment on the existing manual-create owner, not a second writer. */
class RecurringPeriodPaymentSurfaceTest {
    @Test
    fun unpaidOccurrenceSheetExposesRecordPaymentBesideLinkAndClear() {
        val actions = OccurrenceSheetActions::class.members.map { it.name }.toSet()
        assertTrue("onChoose" in actions)
        assertTrue("onSubmit" in actions)
        assertTrue(
            "onRecordPayment" in actions,
            "An unpaid period needs a record-payment action distinct from choosing an existing bill",
        )
    }

    @Test
    fun occurrenceStateCarriesAPeriodPaymentOriginForExistingManualCreate() {
        val fields = RecurringOccurrenceUiState::class.members.map { it.name }.toSet()
        assertTrue(
            "periodPaymentOrigin" in fields,
            "Recreation and offline publish must reuse the captured period origin, not invent a second command",
        )
    }
}
