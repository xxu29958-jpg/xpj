package com.ticketbox.domain.model

/** Both immutable journals belong to one paged read. */
data class ExpenseHistorySnapshot(val revision: Long, val offsetId: Long)

data class ExpenseRevision(
    val publicId: String,
    val revisionNumber: Long,
    val changeKind: String,
    val reason: String,
    val changedFields: List<String>,
    val before: Map<String, Any?>?,
    val after: Map<String, Any?>,
    val actorAccountName: String?,
    val actorDeviceName: String?,
    val createdAt: String,
    val offsetPublicId: String? = null,
)

data class ExpenseRevisionPage(
    val items: List<ExpenseRevision>,
    val page: Int,
    val pageSize: Int,
    val total: Int,
    /** 服务端快照锚：本页 items/total 都属于 revision_number <= 该值的前缀。 */
    val snapshotRevision: Long,
    val offsetSnapshotId: Long = 0,
)

/** One explicit correction intent. Null means the field is unchanged. */
data class ExpenseCorrectionDraft(
    val reason: String,
    val amountCents: Long? = null,
    val originalCurrencyCode: CurrencyCode? = null,
    val originalAmountMinor: Long? = null,
    val merchant: String? = null,
    val category: String? = null,
    val note: String? = null,
    val expenseTime: String? = null,
    /** Distinguishes an omitted time from an explicit clear (`null`). */
    val expenseTimeChanged: Boolean = false,
    val tags: String? = null,
    val valueScore: Int? = null,
    /** Distinguishes an omitted score from an explicit clear (`null`). */
    val valueScoreChanged: Boolean = false,
    val regretScore: Int? = null,
    /** Distinguishes an omitted score from an explicit clear (`null`). */
    val regretScoreChanged: Boolean = false,
    val items: List<ExpenseItemDraft>? = null,
    val splits: List<ExpenseSplitDraft>? = null,
    val timeInput: ExpenseTimeInput? = null,
    val timeInputChanged: Boolean = false,
)
