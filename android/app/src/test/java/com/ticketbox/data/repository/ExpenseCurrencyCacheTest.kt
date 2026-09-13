package com.ticketbox.data.repository

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class ExpenseCurrencyCacheTest {
    @Test
    fun missingHomeCurrencyCannotBecomeCnyInTheCache() {
        listOf(null, "", " ").forEach { missing ->
            assertFailsWith<RepositoryException> {
                confirmedExpenseDtoFixture().copy(homeCurrency = missing).toEntity("owner")
            }
        }
    }

    @Test
    fun missingOriginalCurrencyCannotBecomeCnyInTheCache() {
        listOf(null, "", " ").forEach { missing ->
            assertFailsWith<RepositoryException> {
                confirmedExpenseDtoFixture().copy(
                    originalCurrency = missing, originalCurrencyCode = null,
                ).toEntity("owner")
            }
        }
    }

    @Test
    fun cacheRetainsTheRecordedCurrenciesWithoutRequiringClientEnumSupport() {
        val row = confirmedExpenseDtoFixture().copy(
            homeCurrency = "JPY", originalCurrency = "XXX", originalCurrencyCode = "XXX",
        ).toEntity("owner")

        assertEquals("JPY", row.homeCurrencyCode)
        assertEquals("XXX", row.originalCurrencyCode)
    }
}
