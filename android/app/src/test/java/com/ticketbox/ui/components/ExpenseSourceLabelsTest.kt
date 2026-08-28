package com.ticketbox.ui.components

import com.ticketbox.R
import kotlin.test.Test
import kotlin.test.assertEquals

class ExpenseSourceLabelsTest {
    @Test
    fun webUploadUsesLocalizedProductLabel() {
        assertEquals(
            R.string.expense_edit_source_web,
            expenseSourceLabelRes("网页上传"),
        )
    }
}
