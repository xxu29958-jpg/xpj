package com.ticketbox.ui.navigation

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals

/**
 * Pins the ledger-scoping of transactions-library ViewModel keys: every keyed
 * route must produce a fresh VM identity per ledger so a ledger switch never
 * reuses the previous ledger's state from the back stack (218-B2 review).
 */
class TransactionsLibraryViewModelKeyTest {
    @Test
    fun keyIncludesLedgerIdAndPrefix() {
        assertEquals(
            "category-rules-ledger-a",
            transactionsLibraryViewModelKey("category-rules", "ledger-a"),
        )
        assertEquals(
            "merchant-directory-ledger-a",
            transactionsLibraryViewModelKey("merchant-directory", "ledger-a"),
        )
    }

    @Test
    fun keyDiffersAcrossLedgersForSamePrefix() {
        assertNotEquals(
            transactionsLibraryViewModelKey("category-rules", "ledger-a"),
            transactionsLibraryViewModelKey("category-rules", "ledger-b"),
        )
        assertNotEquals(
            transactionsLibraryViewModelKey("merchant-directory", "ledger-a"),
            transactionsLibraryViewModelKey("merchant-directory", "ledger-b"),
        )
    }

    @Test
    fun nullLedgerFallsBackToNone() {
        assertEquals(
            "tag-directory-none",
            transactionsLibraryViewModelKey("tag-directory", null),
        )
    }

    @Test
    fun recycleBinKeyIsLedgerScopedLikeTheOtherLibraryRoutes() {
        assertEquals(
            "transactions-library-recycle-bin-ledger-a",
            transactionsLibraryViewModelKey("transactions-library-recycle-bin", "ledger-a"),
        )
        assertNotEquals(
            transactionsLibraryViewModelKey("transactions-library-recycle-bin", "ledger-a"),
            transactionsLibraryViewModelKey("transactions-library-recycle-bin", "ledger-b"),
        )
    }
}
