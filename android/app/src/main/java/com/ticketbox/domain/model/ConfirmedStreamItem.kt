package com.ticketbox.domain.model

/**
 * Confirmed ledger stream items (Refund/Chargeback/Reversal 纵向片).
 *
 * Wire envelope (server-owned, request-time current):
 * `{ entry_kind, stream_date, stream_amount_cents, root, offset?, lineage_status,
 *   lineage_home_net_cents }` — every row carries its root, so any visible row's
 * detail destination is offline-openable and the Room root cache self-heals from
 * any entry. [streamDate] and [streamAmountCents] are the only presentation
 * facts grouping/sums may read; clients never recompute amounts or FX.
 *
 * [lineageStatus] / [lineageHomeNetCents] always describe the ROOT's current
 * net state (on offset rows too), never the row's own event.
 */
sealed interface ConfirmedStreamItem {
    val streamDate: String
    val streamAmountCents: Long
    val root: Expense
    val lineageStatus: ExpenseLineageStatus
    val lineageHomeNetCents: Long

    /** Stable LazyColumn key: offset rows share no id space with root expenses. */
    val rowKey: String

    data class ExpenseRow(
        override val streamDate: String,
        override val streamAmountCents: Long,
        override val root: Expense,
        override val lineageStatus: ExpenseLineageStatus,
        override val lineageHomeNetCents: Long,
    ) : ConfirmedStreamItem {
        override val rowKey: String get() = "expense-${root.id}"
    }

    data class OffsetRow(
        override val streamDate: String,
        override val streamAmountCents: Long,
        override val root: Expense,
        override val lineageStatus: ExpenseLineageStatus,
        override val lineageHomeNetCents: Long,
        val offset: StreamOffset,
    ) : ConfirmedStreamItem {
        override val rowKey: String get() = "offset-${offset.publicId}"
    }
}

enum class ExpenseLineageStatus {
    Confirmed,
    PartiallyRefunded,
    FullyRefunded,
    Reversed,
    ;

    /** Root-row state chip copy key; null means no chip (ordinary confirmed). */
    val chipVisible: Boolean get() = this != Confirmed
}

enum class StreamOffsetKind {
    Refund,
    Chargeback,
    Reversal,
    ;

    /** Refund/chargeback carry a signed money slot; reversal is a money-less event row. */
    val isMoneyEvent: Boolean get() = this != Reversal
}

/**
 * The offset event payload (envelope `offset`). `rootExpenseId` and any root
 * merchant label are deliberately absent: the envelope's `root` is the single
 * carrier of root identity and display label.
 * [amountCents] is the home-currency magnitude (positive); direction lives only
 * in the server-owned [ConfirmedStreamItem.streamAmountCents].
 */
data class StreamOffset(
    val publicId: String,
    val kind: StreamOffsetKind,
    val amountCents: Long,
    val originalAmountMinor: Long,
    val originalCurrencyCode: String,
    val homeCurrencyCode: String,
    val category: String,
)

/** Every selectable / batch-command target is an expense root row. */
fun ConfirmedStreamItem.asExpenseRoot(): Expense? =
    (this as? ConfirmedStreamItem.ExpenseRow)?.root

/**
 * Client-side re-filter of the synced stream cache (offline-first): mirrors the
 * server-owned filter semantics over server-owned per-row fields — month =
 * `stream_date`, category = the row's own snapshot (offset category for events,
 * root category for bills), tag = root tags on both kinds. No amount or FX
 * recomputation.
 */
fun filterConfirmedStreamItems(
    items: List<ConfirmedStreamItem>,
    criteria: ExpenseFilterCriteria,
): List<ConfirmedStreamItem> {
    val cleanMonth = criteria.month.trim()
    val cleanCategory = criteria.category.trim()
    val cleanTagKey = criteria.tag.trim().lowercase()
    val cleanQuery = criteria.query.trim().lowercase()
    if (cleanMonth.isNotBlank() && !cleanMonth.matches(Regex("\\d{4}-\\d{2}"))) {
        return emptyList()
    }
    return items.filter { item ->
        val monthMatched = cleanMonth.isBlank() || item.streamDate.startsWith(cleanMonth)
        val categoryMatched = cleanCategory.isBlank() || item.streamCategory() == cleanCategory
        val tagMatched = cleanTagKey.isBlank() || item.root.streamTagNames().any { it.lowercase() == cleanTagKey }
        val queryMatched = cleanQuery.isBlank() || item.streamQueryFields().any { it.lowercase().contains(cleanQuery) }
        monthMatched && categoryMatched && tagMatched && queryMatched
    }
}

private fun ConfirmedStreamItem.streamCategory(): String = when (this) {
    is ConfirmedStreamItem.ExpenseRow -> root.category
    is ConfirmedStreamItem.OffsetRow -> offset.category
}

private fun ConfirmedStreamItem.streamQueryFields(): List<String> = when (this) {
    is ConfirmedStreamItem.ExpenseRow -> listOfNotNull(
        root.merchant,
        root.category,
        root.note,
        root.tags,
        root.source,
    )
    is ConfirmedStreamItem.OffsetRow -> listOfNotNull(
        root.merchant,
        root.note,
        root.tags,
        offset.category,
    )
}

private val STREAM_TAG_SPLIT_REGEX = Regex("[,，;；\\n]+")

private fun Expense.streamTagNames(): List<String> {
    val raw = tags ?: return emptyList()
    val seen = mutableSetOf<String>()
    return STREAM_TAG_SPLIT_REGEX.split(raw)
        .map { it.trim().replace(Regex("\\s+"), " ") }
        .filter { it.isNotBlank() }
        .filter { seen.add(it.lowercase()) }
}
