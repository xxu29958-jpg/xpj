package com.ticketbox.data.repository

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

/**
 * Issue #65 slice 3b: the outbox ``expense:<ref>`` target encoding is the single
 * source of truth shared by the nine expense dispatchers. The load-bearing new
 * behavior is that a device-local ``local:{client_ref}`` ref passes through
 * UNCHANGED — the old per-dispatcher ``removePrefix("expense:").toLongOrNull()``
 * would have mangled it to null and Discarded the row.
 */
class OutboxExpenseTargetTest {
    @Test
    fun `expenseTargetId encodes a server id`() {
        assertEquals("expense:42", expenseTargetId(42L))
    }

    @Test
    fun `parse returns a numeric server-id ref`() {
        assertEquals("42", parseExpenseTargetRef("expense:42"))
    }

    @Test
    fun `parse passes a device-local ref through unchanged`() {
        assertEquals("local:abc-123", parseExpenseTargetRef("expense:local:abc-123"))
    }

    @Test
    fun `parse returns null for a non-expense target`() {
        assertNull(parseExpenseTargetRef("merchant_alias:7"))
        assertNull(parseExpenseTargetRef("garbage"))
    }

    @Test
    fun `build then parse round-trips a server id`() {
        assertEquals("7", parseExpenseTargetRef(expenseTargetId(7L)))
    }
}
