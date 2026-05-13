package com.ticketbox

import android.content.Context
import com.ticketbox.data.local.AppDatabase
import com.ticketbox.data.local.LocalSettingsStore
import com.ticketbox.data.remote.ApiClient
import com.ticketbox.data.repository.BudgetRepository
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.data.repository.RecurringRepository
import com.ticketbox.security.SecureTokenStore

class AppContainer(context: Context) {
    private val appContext = context.applicationContext
    val settingsStore = LocalSettingsStore(appContext)
    val tokenStore = SecureTokenStore(appContext)
    private val database = AppDatabase.getDatabase(appContext)
    private val apiClient = ApiClient(appContext)

    val expenseRepository = ExpenseRepository(
        expenseDao = database.expenseDao(),
        apiClient = apiClient,
        settingsStore = settingsStore,
        tokenStore = tokenStore,
    )

    val ledgerRepository = LedgerRepository(
        apiClient = apiClient,
        settingsStore = settingsStore,
        tokenStore = tokenStore,
        expenseDao = database.expenseDao(),
    )

    val recurringRepository = RecurringRepository(
        apiClient = apiClient,
        settingsStore = settingsStore,
        tokenStore = tokenStore,
    )

    val budgetRepository = BudgetRepository(
        apiClient = apiClient,
        settingsStore = settingsStore,
        tokenStore = tokenStore,
    )
}
