package com.ticketbox.data.repository

import com.ticketbox.domain.model.Expense
import kotlinx.coroutines.flow.Flow

interface GlobalSearchActions {
    fun observeConfirmed(): Flow<List<Expense>>
    suspend fun fetchPending(): Result<List<Expense>>
}
