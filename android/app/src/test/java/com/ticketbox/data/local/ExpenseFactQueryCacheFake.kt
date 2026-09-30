package com.ticketbox.data.local

internal class ExpenseFactQueryCacheFake : ExpenseFactQueryCacheDao {
    private val rows = mutableMapOf<Triple<String, Long, String>, ExpenseFactQueryCacheEntity>()
    override suspend fun saveFactSnapshot(snapshot: ExpenseFactQueryCacheEntity) {
        rows[Triple(snapshot.bindingKey, snapshot.expenseId, snapshot.queryKey)] = snapshot
    }
    override suspend fun factSnapshot(bindingKey: String, expenseId: Long, queryKey: String) = rows[Triple(bindingKey, expenseId, queryKey)]
    override suspend fun clearFactSnapshotsForExpense(bindingKey: String, expenseId: Long) {
        rows.values.removeAll { it.bindingKey == bindingKey && it.expenseId == expenseId }
    }
    override suspend fun clearFactSnapshotsForBinding(bindingKey: String) { rows.values.removeAll { it.bindingKey == bindingKey } }
    override suspend fun clearFactSnapshotsForLedger(ledgerId: String) { rows.values.removeAll { it.ledgerId == ledgerId } }
    override suspend fun clearFactSnapshots() { rows.clear() }
}
