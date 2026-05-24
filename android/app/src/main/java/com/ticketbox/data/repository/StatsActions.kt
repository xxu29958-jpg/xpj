package com.ticketbox.data.repository

import com.ticketbox.domain.model.DataQualitySummary
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.LifestyleStats
import com.ticketbox.domain.model.MonthlyStats
import kotlinx.coroutines.flow.Flow

interface StatsActions {
    fun observeActiveLedgerId(): Flow<String?>
    fun observeConfirmed(): Flow<List<Expense>>
    fun monthlyBudgetCents(): Long?
    fun lastUploadAt(): String?
    suspend fun months(): Result<List<String>>
    suspend fun tags(): Result<List<String>>
    suspend fun monthlyStats(month: String? = null, tag: String? = null): Result<MonthlyStats>
    suspend fun lifestyleStats(month: String? = null): Result<LifestyleStats>
    suspend fun syncConfirmed(
        month: String?,
        category: String?,
        tag: String?,
    ): Result<List<Expense>>
    suspend fun dataQualitySummary(): Result<DataQualitySummary>
}
