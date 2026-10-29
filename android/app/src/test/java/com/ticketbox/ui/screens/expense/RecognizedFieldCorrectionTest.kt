package com.ticketbox.ui.screens.expense

import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.RecognitionFieldCandidate
import org.junit.Assert.assertEquals
import org.junit.Test

class RecognizedFieldCorrectionTest {
    private val paid = RecognitionFieldCandidate("amount_cents", "paid", "12860", "支付金额", "实付 ¥128.60", "原文",
        "payment", true, "fact", "receipt-fields-v8", "CNY", 2)
    private val shop = paid.copy(field = "merchant", id = "merchant", value = "邻里便利店", role = "merchant",
        currencyCode = null, minorUnitExponent = null)

    @Test
    fun amountCorrectionNeedsAValueInTheReadingsCurrencyThatDiffersFromIt() {
        assertEquals(FieldChoiceStatus.Empty, correctionStatus(paid, " ", CurrencyCode.CNY, ""))
        assertEquals(FieldChoiceStatus.Unchanged, correctionStatus(paid, "128.6", CurrencyCode.CNY, ""))
        assertEquals(FieldChoiceStatus.OtherCurrency, correctionStatus(paid, "126.80", CurrencyCode.USD, ""))
        assertEquals(FieldChoiceStatus.Recorded, correctionStatus(paid, "126.80", CurrencyCode.CNY, ""))
    }

    @Test
    fun merchantCorrectionIgnoresSurroundingSpaceButNotADifferentName() {
        assertEquals(FieldChoiceStatus.Empty, correctionStatus(shop, "", CurrencyCode.CNY, "  "))
        assertEquals(FieldChoiceStatus.Unchanged, correctionStatus(shop, "", CurrencyCode.CNY, " 邻里便利店 "))
        assertEquals(FieldChoiceStatus.Recorded, correctionStatus(shop, "", CurrencyCode.CNY, "邻里便利店（东门）"))
    }
}
