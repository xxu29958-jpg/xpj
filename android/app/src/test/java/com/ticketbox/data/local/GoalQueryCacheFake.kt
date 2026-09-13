package com.ticketbox.data.local

internal class GoalQueryCacheFake {
    private val rows = mutableListOf<GoalQueryCacheEntity>()
    fun save(snapshots: List<GoalQueryCacheEntity>) {
        snapshots.forEach { next ->
            rows.removeAll { it.bindingKey == next.bindingKey && it.timezone == next.timezone && it.queryKey == next.queryKey }
            rows.add(next)
        }
    }
    fun find(bindingKey: String, timezone: String, queryKey: String) =
        rows.firstOrNull { it.bindingKey == bindingKey && it.timezone == timezone && it.queryKey == queryKey }
    fun clear(ledgerId: String?) { rows.removeAll { ledgerId == null || it.ledgerId == ledgerId } }
    fun clearBinding(bindingKey: String) { rows.removeAll { it.bindingKey == bindingKey } }
}
