package com.ticketbox.ui.screens

import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.screens.recurring.RecurringEditorSession
import com.ticketbox.ui.screens.recurring.RecurringFormInput
import com.ticketbox.ui.screens.recurring.RecurringFormInvalid
import com.ticketbox.ui.screens.recurring.RecurringFormSubmit
import com.ticketbox.ui.screens.recurring.newRecurringEditorSession
import com.ticketbox.ui.screens.recurring.resolveRecurringFormSubmit
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs

class RecurringCapturedCurrencyEditorTest {
    @Test
    fun `JPY record opens and saves its exact amount under a CNY app default`() {
        val baseline = recurringItem { baselineAmountCents = 1200 }.copy(homeCurrencyCode = "JPY")
        val session = newRecurringEditorSession(baseline, CurrencyCode.CNY)
        assertEquals("JPY", session.homeCurrencyCode)
        assertEquals("1200", session.amountText)
        val result = resolveRecurringFormSubmit(
            baseline, RecurringFormInput(session.merchant, "1300", false, session.dateIso), CurrencyCode.JPY,
        )
        val edit = assertIs<RecurringFormSubmit.Edit>(result)
        assertEquals("JPY", edit.patch.homeCurrencyCode)
        assertEquals(1300L, edit.patch.baselineAmountCents)
        assertEquals(baseline.rowVersion, edit.item.rowVersion)
    }

    @Test
    fun `unknown historical currency cannot become a CNY write`() {
        val baseline = recurringItem { baselineAmountCents = 1200 }.copy(homeCurrencyCode = null)
        val session = newRecurringEditorSession(baseline, CurrencyCode.CNY)
        assertEquals(null, session.homeCurrencyCode)
        assertEquals("1200", session.amountText)
        val result = resolveRecurringFormSubmit(
            baseline, RecurringFormInput(session.merchant, "13.00", false, session.dateIso), CurrencyCode.CNY,
        )
        assertEquals(RecurringFormSubmit.Invalid(RecurringFormInvalid.Currency), result)
    }

    @Test
    fun `new editor captures the chosen currency before the default can change`() {
        val session = newRecurringEditorSession(null, CurrencyCode.JPY)
        val result = resolveRecurringFormSubmit(
            null, RecurringFormInput("交通月票", "1200", false, null),
            requireNotNull(CurrencyCode.fromStorageKeyOrNull(session.homeCurrencyCode)),
        )
        val create = assertIs<RecurringFormSubmit.Create>(result)
        assertEquals("JPY", create.draft.homeCurrencyCode)
        assertEquals(1200L, create.draft.baselineAmountCents)
    }

    @Test
    fun `CNY create entry selects JPY 1200 before the original submit`() {
        val session = newRecurringEditorSession(null, CurrencyCode.CNY)
        assertEquals("CNY", session.homeCurrencyCode)
        session.selectCurrency(CurrencyCode.JPY)
        session.merchant = "交通月票"
        session.amountText = "1200"
        val create = assertIs<RecurringFormSubmit.Create>(submitSession(session))
        assertEquals("JPY", create.draft.homeCurrencyCode)
        assertEquals(1200L, create.draft.baselineAmountCents)
        assertEquals("交通月票", create.draft.merchant)
    }

    @Test
    fun `CNY create entry selects USD 12_34 before the original submit`() {
        val session = newRecurringEditorSession(null, CurrencyCode.CNY)
        session.selectCurrency(CurrencyCode.USD)
        session.merchant = "USD订阅"
        session.amountText = "12.34"
        val create = assertIs<RecurringFormSubmit.Create>(submitSession(session))
        assertEquals("USD", create.draft.homeCurrencyCode)
        assertEquals(1234L, create.draft.baselineAmountCents)
    }

    @Test
    fun `JPY fraction refusal keeps the original create fill`() {
        val session = newRecurringEditorSession(null, CurrencyCode.CNY)
        session.selectCurrency(CurrencyCode.JPY)
        session.merchant = "交通月票"
        session.amountText = "12.34"
        assertEquals(
            RecurringFormSubmit.Invalid(RecurringFormInvalid.Amount),
            submitSession(session),
        )
        assertEquals("JPY", session.homeCurrencyCode)
        assertEquals("12.34", session.amountText)
        assertEquals("交通月票", session.merchant)
    }

    @Test
    fun `recorded editor cannot retarget currency through the create picker`() {
        val baseline = recurringItem { baselineAmountCents = 1200 }.copy(homeCurrencyCode = "JPY")
        val session = newRecurringEditorSession(baseline, CurrencyCode.CNY)
        session.selectCurrency(CurrencyCode.USD)
        assertEquals("JPY", session.homeCurrencyCode)
        assertEquals("1200", session.amountText)
    }

    private fun submitSession(session: RecurringEditorSession): RecurringFormSubmit {
        val currency = requireNotNull(CurrencyCode.fromStorageKeyOrNull(session.homeCurrencyCode))
        return resolveRecurringFormSubmit(
            session.editing,
            RecurringFormInput(session.merchant, session.amountText, session.dateTouched, session.dateIso),
            currency,
        )
    }
}
