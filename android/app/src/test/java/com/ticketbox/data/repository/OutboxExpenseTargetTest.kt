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
 *
 * Slice 4 adds the offline-create encoding ([expenseLocalTargetId]) and the
 * pending-aware selector ([expenseOutboxTargetId]). Extends the outbox test base
 * only to borrow ``baselineExpense()`` for the [Expense] builder.
 */
internal class OutboxExpenseTargetTest : ExpensePendingRepositoryOutboxTestBase() {
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

    @Test
    fun `expenseLocalTargetId encodes a device-local ref`() {
        assertEquals("expense:local:abc-123", expenseLocalTargetId("abc-123"))
    }

    @Test
    fun `expenseLocalTargetId round-trips to a local ref through parse`() {
        assertEquals("local:abc-123", parseExpenseTargetRef(expenseLocalTargetId("abc-123")))
    }

    @Test
    fun `expenseOutboxTargetId targets the local ref while pending`() {
        val pending = baselineExpense().copy(id = -5L, clientRef = "abc-123", pendingSync = true)
        assertEquals("expense:local:abc-123", expenseOutboxTargetId(pending))
    }

    @Test
    fun `expenseOutboxTargetId targets the server id once synced`() {
        // baselineExpense() is a synced row (pendingSync defaults false, clientRef null).
        assertEquals("expense:42", expenseOutboxTargetId(baselineExpense()))
    }

    @Test
    fun `expenseOutboxTargetId falls back to the id for a pending row without a clientRef`() {
        val orphan = baselineExpense().copy(id = -5L, clientRef = null, pendingSync = true)
        assertEquals("expense:-5", expenseOutboxTargetId(orphan))
    }
}
