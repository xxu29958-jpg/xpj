package com.ticketbox.domain.model

/**
 * ADR-0043 slice C — a managed tag with its expense usage count. Distinct from
 * the raw `Expense.tags` delimited string and the autocomplete name list; this
 * is the governance view (rename / delete / merge). `usageCount == 0` is an
 * orphan tag (safe to delete). `rowVersion` is the OCC token.
 */
data class ManagedTag(
    val publicId: String,
    val name: String,
    val usageCount: Int,
    val rowVersion: Long,
)

/**
 * Result of a delete / merge. `sourceTagRowVersion` is the undo token — the
 * soft-deleted source tag's new row_version (契约 2 step ②); pair it with
 * `mutationPublicId` to POST the undo.
 */
data class TagMutationResult(
    val mutationPublicId: String,
    val op: String,
    val sourceTagPublicId: String,
    val sourceTagRowVersion: Long,
    val targetTagPublicId: String?,
    val targetTagRowVersion: Long?,
    val affectedExpenseCount: Int,
)

/** Result of an undo: how many expense snapshots were replayed vs skipped (drifted). */
data class TagUndoResult(
    val restoredTagPublicId: String,
    val restoredTagRowVersion: Long,
    val applied: Int,
    val skipped: Int,
)
