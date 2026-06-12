package com.ticketbox.viewmodel

import com.ticketbox.data.repository.GlobalSearchActions
import com.ticketbox.domain.model.Expense
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow

// Shared fixtures for the two GlobalSearchViewModel test classes.

internal class FakeGlobalSearchActions(
    private val activeLedgerFlow: Flow<String?> = MutableStateFlow("owner"),
    pending: List<Expense> = emptyList(),
    pendingResult: Result<List<Expense>> = Result.success(pending),
    confirmed: List<Expense> = emptyList(),
    initialRecent: List<String> = emptyList(),
) : GlobalSearchActions {
    private val confirmedFlow = MutableStateFlow(confirmed)
    var pendingResult = pendingResult
    var fetchPendingResponder: (suspend () -> Result<List<Expense>>)? = null
    var fetchPendingCalls: Int = 0
        private set

    // Mirrors the SharedPreferences-backed store: last write wins, read-back
    // returns it. Lets the VM tests assert persistence round-trips.
    var savedRecent: List<String> = initialRecent
        private set

    override fun observeActiveLedgerId(): Flow<String?> = activeLedgerFlow

    override fun observeConfirmed(): Flow<List<Expense>> = confirmedFlow

    override suspend fun fetchPending(): Result<List<Expense>> {
        fetchPendingCalls += 1
        fetchPendingResponder?.let { return it() }
        return pendingResult
    }

    override fun recentSearches(): List<String> = savedRecent

    override fun saveRecentSearches(queries: List<String>) {
        savedRecent = queries
    }
}

// Five params keeps detekt's LongParameterList honest; tests needing the rarer
// fields (expenseTime / originalAmountMinor) `.copy(...)` the result.
internal fun expense(
    id: Long,
    status: String,
    merchant: String,
    amountCents: Long? = 1200L,
    category: String = "餐饮",
): Expense = Expense(
    id = id,
    publicId = "exp-$id",
    amountCents = amountCents,
    originalAmountMinor = null,
    merchant = merchant,
    category = category,
    note = "家庭周末",
    source = "manual",
    imagePath = null,
    thumbnailPath = null,
    imageHash = null,
    rawText = "Search raw text",
    confidence = null,
    duplicateStatus = "none",
    duplicateOfId = null,
    duplicateReason = null,
    tags = "family",
    valueScore = null,
    regretScore = null,
    status = status,
    expenseTime = "2026-05-17T08:00:00Z",
    createdAt = "2026-05-17T08:00:00Z",
    updatedAt = "2026-05-17T08:00:00Z",
    rowVersion = 1L,
    confirmedAt = if (status == "confirmed") "2026-05-17T08:01:00Z" else null,
    rejectedAt = null,
)
