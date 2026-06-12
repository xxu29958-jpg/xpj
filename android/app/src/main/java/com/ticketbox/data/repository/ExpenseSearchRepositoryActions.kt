package com.ticketbox.data.repository

import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.domain.model.Expense
import kotlinx.coroutines.flow.Flow

internal class ExpenseSearchRepositoryActions(
    private val core: ExpenseRepositoryCore,
    private val pendingActions: PendingReviewActions,
    private val settingsStore: TicketboxSettingsStore,
) : GlobalSearchActions {
    override fun observeActiveLedgerId(): Flow<String?> = core.observeActiveLedgerId()

    override fun observeConfirmed(): Flow<List<Expense>> = core.observeConfirmed()

    override suspend fun fetchPending(): Result<List<Expense>> = pendingActions.fetchPending()

    override fun recentSearches(): List<String> = settingsStore.recentSearches()

    override fun saveRecentSearches(queries: List<String>) = settingsStore.saveRecentSearches(queries)
}
