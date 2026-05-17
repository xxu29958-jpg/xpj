package com.ticketbox.data.repository

import com.ticketbox.domain.model.Expense
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow

interface GlobalSearchActions {
    fun observeActiveLedgerId(): Flow<String?> = emptyFlow()
    fun observeConfirmed(): Flow<List<Expense>>
    suspend fun fetchPending(): Result<List<Expense>>
}
