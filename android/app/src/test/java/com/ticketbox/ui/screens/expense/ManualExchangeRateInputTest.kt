package com.ticketbox.ui.screens.expense

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class ManualExchangeRateInputTest {
    @Test
    fun inputSanitizerPreservesInvalidIntentForVisibleValidation() {
        assertEquals("-1", sanitizeManualExchangeRateInput("-1"))
        assertEquals("1e3", sanitizeManualExchangeRateInput("1e3"))
        assertEquals("1,25", sanitizeManualExchangeRateInput("1,25"))
    }

    @Test
    fun canonicalRateAcceptsPositiveExactDecimalAndRejectsAmbiguousValues() {
        assertEquals("0.048", canonicalManualExchangeRateOrNull(" 0.048 "))
        assertEquals("7.20", canonicalManualExchangeRateOrNull("7.20"))
        assertNull(canonicalManualExchangeRateOrNull(""))
        assertNull(canonicalManualExchangeRateOrNull("0"))
        assertNull(canonicalManualExchangeRateOrNull("07.2"))
        assertNull(canonicalManualExchangeRateOrNull(".5"))
        assertNull(canonicalManualExchangeRateOrNull("1e2"))
        assertNull(canonicalManualExchangeRateOrNull("0.000000001"))
        assertNull(canonicalManualExchangeRateOrNull("10000000000"))
    }

    @Test
    fun pendingAndChangedManualRatesRequireServerReviewBeforeConfirm() {
        assertTrue(
            manualExchangeRateNeedsServerReview(
                fxPending = true,
                savedManualRate = null,
                draftManualRate = "7.20",
                fxIdentityChanged = false,
            ),
        )
        assertFalse(
            manualExchangeRateNeedsServerReview(
                fxPending = false,
                savedManualRate = "7.20",
                draftManualRate = "7.20",
                fxIdentityChanged = false,
            ),
        )
        assertTrue(
            manualExchangeRateNeedsServerReview(
                fxPending = false,
                savedManualRate = "7.20",
                draftManualRate = "7.25",
                fxIdentityChanged = false,
            ),
        )
        assertTrue(
            manualExchangeRateNeedsServerReview(
                fxPending = false,
                savedManualRate = "7.20",
                draftManualRate = "7.20",
                fxIdentityChanged = true,
            ),
        )
    }

    @Test
    fun editorAppearsOnlyForPendingForeignRecoveryOrExistingManualSnapshot() {
        assertTrue(
            manualExchangeRateEditorVisible(
                pendingExpense = true,
                foreignCurrency = true,
                fxPending = true,
                fxSource = null,
            ),
        )
        assertTrue(
            manualExchangeRateEditorVisible(
                pendingExpense = true,
                foreignCurrency = true,
                fxPending = false,
                fxSource = "manual",
            ),
        )
        assertFalse(
            manualExchangeRateEditorVisible(
                pendingExpense = true,
                foreignCurrency = true,
                fxPending = false,
                fxSource = "ecb",
            ),
        )
        assertFalse(
            manualExchangeRateEditorVisible(
                pendingExpense = true,
                foreignCurrency = false,
                fxPending = true,
                fxSource = null,
            ),
        )
    }
}
