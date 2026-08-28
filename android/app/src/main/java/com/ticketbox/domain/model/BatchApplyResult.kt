package com.ticketbox.domain.model

/** Outcome of one server-owned, atomic confirmed-expense correction command. */
data class BatchApplyResult(
    val requested: Int,
    val updated: Int,
    val skippedNotFound: Int,
    val skippedNotConfirmed: Int,
) {
    val skipped: Int get() = skippedNotFound + skippedNotConfirmed
}
