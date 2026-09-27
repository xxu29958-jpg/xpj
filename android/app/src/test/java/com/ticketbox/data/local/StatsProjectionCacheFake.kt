package com.ticketbox.data.local

internal class StatsProjectionCacheFake {
    private val rows = mutableListOf<StatsProjectionCacheEntity>()
    private val proofKinds = setOf("recurring_direct_barrier", "recurring_outbox_read_barrier", "recurring_read_epoch")
    fun save(row: StatsProjectionCacheEntity) {
        rows.removeAll { it.bindingKey == row.bindingKey && it.kind == row.kind && it.month == row.month &&
            it.tag == row.tag && it.homeCurrencyCode == row.homeCurrencyCode && it.timezone == row.timezone }
        rows.add(row)
    }
    fun find(bindingKey: String, kind: String, month: String, tag: String, timezone: String) =
        rows.filter { it.bindingKey == bindingKey && it.kind == kind && it.month == month && it.tag == tag &&
            it.timezone == timezone }
            .sortedByDescending { it.fetchedAt }
    fun clear(ledgerId: String?) { rows.removeAll { it.kind !in proofKinds && (ledgerId == null || it.ledgerId == ledgerId) } }
    fun budgetMonth(bindingKey: String, month: String) =
        rows.filter { it.bindingKey == bindingKey && it.kind == "budget" && it.month == month }
    fun delete(row: StatsProjectionCacheEntity) { rows.remove(row) }
    fun clearBinding(bindingKey: String) { rows.removeAll { it.bindingKey == bindingKey && it.kind !in proofKinds } }
    fun clearRecurring(bindingKey: String) {
        rows.removeAll { it.bindingKey == bindingKey && it.kind in setOf("recurring_items", "recurring_history", "recurring_occurrence") }
    }
}
