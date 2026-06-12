package com.ticketbox.data.repository

import com.ticketbox.domain.model.Expense
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow

interface GlobalSearchActions {
    fun observeActiveLedgerId(): Flow<String?> = emptyFlow()
    fun observeConfirmed(): Flow<List<Expense>>
    suspend fun fetchPending(): Result<List<Expense>>

    /** Recently committed search queries, most-recent-first (see
     *  [com.ticketbox.data.local.TicketboxSettingsStore.recentSearches]). */
    fun recentSearches(): List<String> = emptyList()

    fun saveRecentSearches(queries: List<String>) = Unit
}
