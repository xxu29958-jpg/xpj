package com.ticketbox.data.local

internal class StatsProjectionCacheFake {
    private val rows = mutableListOf<StatsProjectionCacheEntity>()
    fun save(row: StatsProjectionCacheEntity) {
        rows.removeAll { it.bindingKey == row.bindingKey && it.kind == row.kind && it.month == row.month &&
            it.tag == row.tag && it.homeCurrencyCode == row.homeCurrencyCode && it.timezone == row.timezone }
        rows.add(row)
    }
    fun find(bindingKey: String, kind: String, month: String, tag: String, timezone: String) =
        rows.filter { it.bindingKey == bindingKey && it.kind == kind && it.month == month && it.tag == tag &&
            it.timezone == timezone }
            .sortedByDescending { it.fetchedAt }
    fun clear(ledgerId: String?) { rows.removeAll { ledgerId == null || it.ledgerId == ledgerId } }
}
