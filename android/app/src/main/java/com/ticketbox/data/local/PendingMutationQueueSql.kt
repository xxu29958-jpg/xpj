package com.ticketbox.data.local

/** Shared by runnable selection, target inspection and the atomic claim. Other states always block. */
internal const val OUTBOX_FAILED_ROW_BLOCKS = "(sib.status != 'failed' OR sib.blocksFollowing = 1)"

/**
 * Both selection and claim use the original persisted FIFO, including rows already tried this pass.
 * Excluding a previously attempted candidate must never make its later sibling the head.
 */
internal const val OUTBOX_NO_EARLIER_PENDING_SIBLING = """
    NOT EXISTS (
        SELECT 1 FROM pending_mutations AS older
        WHERE older.ownerKey = pending_mutations.ownerKey
          AND older.ledgerId = pending_mutations.ledgerId
          AND older.targetId = pending_mutations.targetId
          AND older.status = pending_mutations.status
          AND (
              older.createdAt < pending_mutations.createdAt
              OR (older.createdAt = pending_mutations.createdAt AND older.id < pending_mutations.id)
          )
    )
"""
