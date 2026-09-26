package com.ticketbox.data.repository
import com.ticketbox.data.local.MonthlyArrangementCacheDao
import com.ticketbox.data.local.MonthlyArrangementCacheEntity
internal class FakeMonthlyArrangementCacheDao : MonthlyArrangementCacheDao {
    private val rows = mutableMapOf<Triple<String, String, String>, MonthlyArrangementCacheEntity>()
    fun readSnapshotBindings() = rows.values.filter { it.kind != "draft" }.map { it.bindingKey }.distinct()
    fun clearReadSnapshots(bindingKey: String? = null) {
        rows.entries.removeAll { it.value.kind != "draft" && (bindingKey == null || it.value.bindingKey == bindingKey) }
    }
    override suspend fun read(bindingKey: String, month: String, kind: String) = rows[Triple(bindingKey, month, kind)]
    override suspend fun write(row: MonthlyArrangementCacheEntity) { rows[Triple(row.bindingKey, row.month, row.kind)] = row }
    override suspend fun consumeDraft(bindingKey: String, month: String, expectedJson: String) {
        val key = Triple(bindingKey, month, "draft")
        if (rows[key]?.json == expectedJson) rows.remove(key)
    }
}
