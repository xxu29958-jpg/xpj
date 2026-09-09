package com.ticketbox.data.repository

import com.ticketbox.domain.model.DataQualitySummary
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.LifestyleStats
import com.ticketbox.domain.model.MonthlyStats
import kotlinx.coroutines.flow.Flow

interface StatsActions {
    fun observeStatsBinding(): Flow<LogicalSessionBinding?>
    fun statsBinding(): LogicalSessionBinding?
    fun lastUploadAt(): String?
    suspend fun months(): Result<List<String>>
    suspend fun tags(): Result<List<String>>
    suspend fun monthlyStats(query: StatsQuery): Result<StatsRead<MonthlyStats>>
    suspend fun lifestyleStats(query: StatsQuery): Result<StatsRead<LifestyleStats>>
    suspend fun syncConfirmed(
        month: String?,
        category: String?,
        tag: String?,
    ): Result<List<Expense>>
    suspend fun dataQualitySummary(): Result<DataQualitySummary>
}

data class StatsQuery(
    val binding: LogicalSessionBinding,
    val month: String,
    val tag: String = "",
    val homeCurrencyCode: String? = null,
    val timezone: String = java.util.TimeZone.getDefault().id,
)

data class StatsRead<T>(val value: T, val fetchedAt: String, val fromCache: Boolean)
