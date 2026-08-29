package com.ticketbox.domain.model

/** Receipt returned after the upload itself is durably accepted. */
data class PendingUploadReceipt(
    val expenseId: Long,
    val enrichmentTaskPublicId: String,
)

/** Typed projection of the existing ``expense_enrichment`` background task. */
data class PendingEnrichmentTask(
    val status: String,
    val outcome: PendingEnrichmentOutcome?,
)

enum class PendingEnrichmentOutcome {
    Updated,
    NoResult,
    NotPending,
    Conflict,
}
