package com.ticketbox.data.repository

import com.ticketbox.domain.model.Expense

/**
 * Single source of truth for the outbox ``expense:<ref>`` target encoding (issue #65 slice 3).
 *
 * ``<ref>`` is either a server id or a device-local ``local:{client_ref}`` (the offline
 * manual-create path that produces local refs lands in slice 4). The backend's
 * ``resolve_expense_for_mutation`` resolves either form, so a dispatcher hands the ref straight
 * to the mutation route's string path param without caring which it is — keeping the encoding
 * knowledge in one place instead of duplicated across the nine expense dispatchers.
 */
private const val EXPENSE_TARGET_PREFIX = "expense:"
private const val LOCAL_REF_PREFIX = "local:"

/** The outbox ``targetId`` for a synced expense addressed by its server id. */
fun expenseTargetId(serverId: Long): String = "$EXPENSE_TARGET_PREFIX$serverId"

/**
 * The outbox ``targetId`` for a not-yet-synced offline create addressed by its device-local
 * client ref — ``expense:local:{clientRef}`` (issue #65 slice 4). ``parseExpenseTargetRef``
 * returns ``local:{clientRef}``, which the backend's ``resolve_expense`` maps to the row via
 * its ``draft_idempotency_key``. Sharing the same ``targetId`` with the row's CreateExpense
 * means the drain's per-target serial guard replays the create BEFORE any later edit.
 */
fun expenseLocalTargetId(clientRef: String): String = "$EXPENSE_TARGET_PREFIX$LOCAL_REF_PREFIX$clientRef"

/**
 * The outbox ``targetId`` for a mutation against [expense]: the device-local target while it is
 * still [Expense.pendingSync] (no server id yet — address it by [Expense.clientRef]), else the
 * server-id target. Centralises the "synced vs not" branch so every enqueue/guard site agrees;
 * a pending row whose [Expense.clientRef] is somehow absent falls back to the (negative) id
 * target, which the backend would 404 — surfaced rather than silently mis-routed.
 */
fun expenseOutboxTargetId(expense: Expense): String {
    val clientRef = expense.clientRef
    return if (expense.pendingSync && clientRef != null) {
        expenseLocalTargetId(clientRef)
    } else {
        expenseTargetId(expense.id)
    }
}

/**
 * The expense ref to send as a mutation route's path param — the part after ``expense:``
 * (a numeric server id, or ``local:{client_ref}``) — or ``null`` when ``targetId`` is not an
 * expense target (the dispatcher then Discards the row as malformed).
 */
fun parseExpenseTargetRef(targetId: String): String? =
    if (targetId.startsWith(EXPENSE_TARGET_PREFIX)) {
        targetId.removePrefix(EXPENSE_TARGET_PREFIX)
    } else {
        null
    }
