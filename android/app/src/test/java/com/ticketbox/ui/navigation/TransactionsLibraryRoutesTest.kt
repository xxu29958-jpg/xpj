package com.ticketbox.ui.navigation

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class TransactionsLibraryRoutesTest {
    @Test
    fun allLibraryDestinationsAreNamespacedUnderTransactions() {
        val destinations = setOf(
            TRANSACTIONS_LIBRARY_OVERVIEW_ROUTE,
            TRANSACTIONS_LIBRARY_CATEGORIES_ROUTE,
            TRANSACTIONS_LIBRARY_MERCHANTS_ROUTE,
            TRANSACTIONS_LIBRARY_TAGS_ROUTE,
            TRANSACTIONS_LIBRARY_RULES_ROUTE,
            TRANSACTIONS_LIBRARY_RECYCLE_BIN_ROUTE,
        )

        assertEquals(6, destinations.size)
        assertTrue(destinations.all { it.startsWith("$TRANSACTIONS_LIBRARY_ROUTE/") })
    }
}
