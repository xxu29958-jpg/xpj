package com.ticketbox.data.local

import androidx.room.Entity
import androidx.room.Index

/** A server read receipt, never an aggregate of the local expense cache. */
@Entity(
    tableName = "stats_projection_cache",
    primaryKeys = ["bindingKey", "kind", "month", "tag", "homeCurrencyCode", "timezone"],
    indices = [Index("ledgerId")],
)
data class StatsProjectionCacheEntity(
    val bindingKey: String,
    val ledgerId: String,
    val kind: String,
    val month: String,
    val tag: String,
    val homeCurrencyCode: String,
    val timezone: String,
    val responseJson: String,
    val fetchedAt: String,
)
