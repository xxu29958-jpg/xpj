package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.ExpenseTimeInputDto
import com.ticketbox.ui.screens.expense.ExpenseEditFormValues
import com.ticketbox.viewmodel.ExpenseFactInputCodec
import com.ticketbox.viewmodel.ExpenseFactInputDraft
import com.ticketbox.viewmodel.confirmationTimeForm
import com.ticketbox.viewmodel.readExpenseTimeForm
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

internal class ExpenseConfirmationRecoveryTest : ExpensePendingRepositoryOutboxTestBase() {
    @Test fun `reopening an atomic rejection retains its edits through durable input serialization`() {
        val baseline = baselineExpense()
        val changes = draft.toRequest(baseline).copy(originalAmount = "12.90", merchant = "", note = "核对备注",
            timeInput = ExpenseTimeInputDto("date_only", 1, "2026-11-01", accountingDate = "2026-11-01"))
        val original = ExpenseFactInputDraft(baseline, fundingJson = "[]", confirmationChanges = changes)
        val restored = ExpenseFactInputCodec.decode(ExpenseFactInputCodec.encode(original), baseline.id)
        val form = ExpenseEditFormValues.fromConfirmation(baseline, restored.confirmationChanges)
        assertEquals("12.90", form.amountText)
        assertEquals("", form.merchant)
        assertEquals("核对备注", form.note)
        val time = requireNotNull(readExpenseTimeForm(confirmationTimeForm(baseline, restored.confirmationChanges)))
        assertTrue(time.changed)
        assertEquals("2026-11-01", time.resolve().input?.userLocalDate)
        assertEquals("date_only", time.resolve().input?.precision)
        assertEquals(changes, restored.confirmationChanges)
    }
}
