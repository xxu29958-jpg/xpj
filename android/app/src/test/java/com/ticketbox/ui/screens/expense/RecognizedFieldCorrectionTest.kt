package com.ticketbox.ui.screens.expense

import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.RecognitionFieldCandidate
import org.junit.Assert.assertEquals
import org.junit.Test

class RecognizedFieldCorrectionTest {
    private val paid = RecognitionFieldCandidate("amount_cents", "paid", "12860", "支付金额", "实付 ¥128.60", "原文",
        "payment", true, "fact", "receipt-fields-v8", "CNY", 2, sourceReadingValue = "12860")
    private val shop = paid.copy(field = "merchant", id = "merchant", value = "邻里便利店", sourceReadingValue = "邻里便利店",
        role = "merchant", currencyCode = null, minorUnitExponent = null)

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

    @Test
    fun recalledSuggestionIsComparedWithTheParsersOwnReadingNotWithItself() {
        // The parser read 18.00 / 海棠咖吽; personal recall now shows 1.80 / 海棠咖啡.
        val amount = paid.copy(value = "180", sourceReadingValue = "1800", selectionIntent = "bookkeeping")
        val merchant = shop.copy(value = "海棠咖啡", sourceReadingValue = "海棠咖吽", selectionIntent = "bookkeeping")
        assertEquals(FieldChoiceStatus.Recorded, correctionStatus(amount, "1.80", CurrencyCode.CNY, ""))
        assertEquals(FieldChoiceStatus.Unchanged, correctionStatus(amount, "18.00", CurrencyCode.CNY, ""))
        assertEquals(FieldChoiceStatus.Recorded, correctionStatus(merchant, "", CurrencyCode.CNY, "海棠咖啡"))
        assertEquals(FieldChoiceStatus.Unchanged, correctionStatus(merchant, "", CurrencyCode.CNY, "海棠咖吽"))
    }

    @Test
    fun missingSourceReadingNeverFallsBackToThePossiblyRecalledValue() {
        assertEquals(FieldChoiceStatus.SourceUnavailable,
            correctionStatus(paid.copy(sourceReadingValue = null), "1.80", CurrencyCode.CNY, ""))
        assertEquals(FieldChoiceStatus.SourceUnavailable,
            correctionStatus(shop.copy(sourceReadingValue = null), "", CurrencyCode.CNY, "海棠咖啡"))
    }
}
