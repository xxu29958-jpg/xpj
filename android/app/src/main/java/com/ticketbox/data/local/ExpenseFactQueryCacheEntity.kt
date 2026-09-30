package com.ticketbox.data.local

import androidx.room.Entity
import androidx.room.Index

/** Rebuildable, authorized reads. Original human input and Outbox commands live separately. */
@Entity(tableName = "expense_fact_query_cache", primaryKeys = ["bindingKey", "expenseId", "queryKey"],
    indices = [Index("ledgerId")])
data class ExpenseFactQueryCacheEntity(
    val bindingKey: String,
    val ledgerId: String,
    val expenseId: Long,
    val queryKey: String,
    val responseJson: String,
    val fetchedAt: String,
)
