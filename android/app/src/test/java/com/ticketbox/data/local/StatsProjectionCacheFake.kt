package com.ticketbox.data.local

internal class StatsProjectionCacheFake {
    private val rows = mutableListOf<StatsProjectionCacheEntity>()
    private val proofKinds = setOf("debt_direct_barrier", "debt_outbox_read_barrier", "debt_read_epoch")
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
    fun byKind(bindingKey: String, kind: String) = rows.filter { it.bindingKey == bindingKey && it.kind == kind }
    fun clearKinds(bindingKey: String, kinds: Set<String>) { rows.removeAll { it.bindingKey == bindingKey && it.kind in kinds } }
}
