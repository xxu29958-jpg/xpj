package com.ticketbox.data.repository

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

/** The outbox ``targetId`` for a synced expense addressed by its server id. */
fun expenseTargetId(serverId: Long): String = "$EXPENSE_TARGET_PREFIX$serverId"

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
