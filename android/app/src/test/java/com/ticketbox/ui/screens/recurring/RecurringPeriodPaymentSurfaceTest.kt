package com.ticketbox.ui.screens.recurring

import com.ticketbox.viewmodel.RecurringOccurrenceUiState
import com.ticketbox.viewmodel.RecurringPeriodPaymentOrigin
import java.io.File
import kotlin.test.Test
import kotlin.test.assertFalse
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

    @Test
    fun periodPaymentOriginKeepsDraftFieldsNeededForRecreation() {
        val fields = RecurringPeriodPaymentOrigin::class.members.map { it.name }.toSet()
        for (name in listOf("category", "note", "ledgerHomeCurrencyCode")) {
            assertTrue(name in fields, "Recreation must keep $name on the captured period-payment origin")
        }
    }

    @Test
    fun unknownObligationCurrencyDoesNotGuessLedgerHomeOnTheExistingManualSheet() {
        val host = listOf(
            File("src/main/java/com/ticketbox/ui/navigation/RecurringOccurrenceRoute.kt"),
            File("app/src/main/java/com/ticketbox/ui/navigation/RecurringOccurrenceRoute.kt"),
        ).first { it.exists() }.readText()
        assertFalse(
            "?: CurrencyCode.CNY" in host,
            "A legacy unpaid period cannot open the existing manual sheet by guessing the ledger home currency",
        )
    }

    @Test
    fun periodPaymentSessionDoesNotDeriveLedgerHomeFromConfirmedPayments() {
        val session = listOf(
            File("src/main/java/com/ticketbox/viewmodel/RecurringPeriodPaymentSession.kt"),
            File("app/src/main/java/com/ticketbox/viewmodel/RecurringPeriodPaymentSession.kt"),
        ).first { it.exists() }.readText()
        assertFalse(
            "payments.firstOrNull()" in session,
            "Ledger home must come from the ledger capability, not the first confirmed payment",
        )
        assertTrue(
            "SavedStateHandle" in session,
            "The return-to-period origin must survive process restoration on saved state",
        )
    }

    @Test
    fun occurrenceLoadUsesSharedLedgerCurrencyAuthority() {
        val vm = listOf(
            File("src/main/java/com/ticketbox/viewmodel/RecurringOccurrenceViewModel.kt"),
            File("app/src/main/java/com/ticketbox/viewmodel/RecurringOccurrenceViewModel.kt"),
        ).first { it.exists() }.readText()
        assertTrue(
            "resolveLedgerCurrency" in vm,
            "Period payment must reuse the shared ledger-currency authority, not the envelope field alone",
        )
        assertFalse(
            "page.ledgerHomeCurrencyCode" in vm,
            "Envelope capability is an input to resolveLedgerCurrency, not the final home currency",
        )
    }

    @Test
    fun periodPaymentHostReportsBusyAndCreateFailureOnTheExistingManualSheet() {
        val host = listOf(
            File("src/main/java/com/ticketbox/ui/navigation/RecurringOccurrenceRoute.kt"),
            File("app/src/main/java/com/ticketbox/ui/navigation/RecurringOccurrenceRoute.kt"),
        ).first { it.exists() }.readText()
        val vm = listOf(
            File("src/main/java/com/ticketbox/viewmodel/RecurringOccurrenceViewModel.kt"),
            File("app/src/main/java/com/ticketbox/viewmodel/RecurringOccurrenceViewModel.kt"),
        ).first { it.exists() }.readText()
        val session = listOf(
            File("src/main/java/com/ticketbox/viewmodel/RecurringPeriodPaymentSession.kt"),
            File("app/src/main/java/com/ticketbox/viewmodel/RecurringPeriodPaymentSession.kt"),
        ).first { it.exists() }.readText()
        assertTrue("saving = state.periodPaymentSaving" in host)
        assertTrue("errorMessage = state.periodPaymentError" in host)
        assertTrue("createPeriodPayment" in host)
        assertTrue("ManualExpenseSheetInitials" in host)
        assertTrue("origin.merchant" in host)
        assertTrue("capturedAmountCents" in host)
        assertFalse("ledger.createManualExpense" in host)
        assertFalse("markPeriodPaymentCreate" in host)
        assertTrue("createPeriodPayment" in vm)
        assertTrue("submitted.binding" in vm)
        assertTrue("ledger_msg_manual_save_failed" in vm)
        assertFalse("markPeriodPaymentCreate" in vm)
        assertTrue("fun acceptPeriodPaymentAdmission(clientRef: String" in session)
        assertTrue("fun capturePeriodPaymentDraft(" in session && "clientRef: String" in session)
        assertTrue("preferredPaymentClientRef" in RecurringOccurrenceUiState::class.members.map { it.name }.toSet())
        assertTrue("preferredPaymentAcceptedExpenseId" in RecurringOccurrenceUiState::class.members.map { it.name }.toSet())
        assertTrue("acceptedExpenseId" in RecurringPeriodPaymentOrigin::class.members.map { it.name }.toSet())
        assertTrue("choosePeriodPaymentCurrency" in host)
        assertTrue("preferredExpenseId" in File("src/main/java/com/ticketbox/ui/screens/recurring/RecurringOccurrenceSheet.kt").let { if (it.exists()) it else File("app/src/main/java/com/ticketbox/ui/screens/recurring/RecurringOccurrenceSheet.kt") }.readText())
    }
}
