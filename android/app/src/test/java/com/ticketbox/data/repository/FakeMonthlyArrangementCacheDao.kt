package com.ticketbox.data.repository
import com.ticketbox.data.local.MonthlyArrangementCacheDao
import com.ticketbox.data.local.MonthlyArrangementCacheEntity
internal class FakeMonthlyArrangementCacheDao : MonthlyArrangementCacheDao {
    private val rows = mutableMapOf<Triple<String, String, String>, MonthlyArrangementCacheEntity>()
    override suspend fun read(bindingKey: String, month: String, kind: String) = rows[Triple(bindingKey, month, kind)]
    override suspend fun write(row: MonthlyArrangementCacheEntity) { rows[Triple(row.bindingKey, row.month, row.kind)] = row }
    override suspend fun removeDraft(bindingKey: String, month: String) { rows.remove(Triple(bindingKey, month, "draft")) }
}
