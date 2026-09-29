package com.ticketbox.data.local

import com.squareup.moshi.JsonDataException
import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import java.io.IOException

/** Metadata of the existing query cache, including every debt needed by an aggregate. */
@JsonClass(generateAdapter = true)
internal data class DebtQueryCachePayload(
    val epoch: Long,
    val sequence: Long,
    val response: String,
    val readOwner: String,
    val resources: Set<String> = emptySet(),
)

internal val debtQueryCacheAdapter = Moshi.Builder().build()
    .adapter(DebtQueryCachePayload::class.java)

internal fun StatsProjectionCacheEntity.debtCachePayload(): DebtQueryCachePayload? =
    try { debtQueryCacheAdapter.fromJson(responseJson) }
    catch (_: IOException) { null }
    catch (_: JsonDataException) { null }
