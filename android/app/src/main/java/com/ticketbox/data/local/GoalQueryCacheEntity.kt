package com.ticketbox.data.local

import androidx.room.Entity
import androidx.room.Index

/** Complete list or detail read; original commands and their receipts stay in the Outbox. */
@Entity(
    tableName = "goal_query_cache",
    primaryKeys = ["bindingKey", "timezone", "queryKey"],
    indices = [Index("ledgerId")],
)
data class GoalQueryCacheEntity(
    val bindingKey: String,
    val ledgerId: String,
    val timezone: String,
    val queryKey: String,
    val responseJson: String,
    val fetchedAt: String,
)
