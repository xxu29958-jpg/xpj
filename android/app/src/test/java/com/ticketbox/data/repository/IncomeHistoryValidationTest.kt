package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.IncomeDefinitionDto
import com.ticketbox.data.remote.dto.IncomeHistoryResponseDto
import com.ticketbox.data.remote.dto.IncomeRevisionDto
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull

class IncomeHistoryValidationTest {
    private val binding = LogicalSessionBinding("https://income.example", "household", "owner", "session", "revision")
    private val definition = IncomeDefinitionDto("原收入预测", "salary", "one_time", "2026-11", 1200, "JPY", 31, "archived")
    private val original = IncomeRevisionDto(3, "edit", "2026-09-28T10:00:00Z", "2026-09", "2026-09", definition)
    private val page = IncomeHistoryResponseDto("household", "income", listOf(original), null)

    @Test fun readPreservesZeroDecimalCurrencyScheduledMonthAndUnknownBaseline() {
        page.validateIncomeHistory(binding, "income", null)
        assertEquals(1200L, page.toDomain().items.single().snapshot.amountCents)
        assertEquals("2026-11", page.toDomain().items.single().snapshot.incomeMonth)
        val baseline = page.copy(items = listOf(original.copy(changeKind = "baseline", intentMonth = null,
            effectiveMonth = null, snapshot = definition.copy(homeCurrencyCode = null))))
        baseline.validateIncomeHistory(binding, "income", null)
        assertNull(baseline.toDomain().items.single().snapshot.homeCurrencyCode)
        assertNull(baseline.toDomain().items.single().effectiveMonth)
    }

    @Test fun mismatchedEnvelopeAndRepeatedPagesCannotBecomeReadHistory() {
        val invalid = listOf(page.copy(ledgerId = "other"), page.copy(publicId = "other"),
            page.copy(items = listOf(original, original)), page.copy(nextBeforeVersion = 2),
            page.copy(items = emptyList(), nextBeforeVersion = 3))
        invalid.forEach { assertFailsWith<IllegalArgumentException> { it.validateIncomeHistory(binding, "income", null) } }
        assertFailsWith<IllegalArgumentException> { page.validateIncomeHistory(binding, "income", 3) }
    }

    @Test fun partialMonthsAndInvalidDefinitionsCannotBeDisplayedAsAcceptedFacts() {
        val invalid = listOf(original.copy(intentMonth = null), original.copy(effectiveMonth = null),
            original.copy(changeKind = "baseline"), original.copy(snapshot = definition.copy(amountCents = -1)),
            original.copy(snapshot = definition.copy(frequency = "monthly")),
            original.copy(snapshot = definition.copy(payDay = 0)))
        invalid.forEach { row ->
            assertFailsWith<IllegalArgumentException> { page.copy(items = listOf(row)).validateIncomeHistory(binding, "income", null) }
        }
    }
}
