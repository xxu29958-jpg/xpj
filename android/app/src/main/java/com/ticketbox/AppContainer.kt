package com.ticketbox

import android.content.Context
import com.ticketbox.data.local.AppDatabase
import com.ticketbox.data.local.LocalSettingsStore
import com.ticketbox.data.remote.ApiClient
import com.ticketbox.data.repository.ApiServiceProvider
import com.ticketbox.data.repository.BudgetRepository
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.IncomePlanRepository
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.data.repository.LocalLedgerSessionCoordinator
import com.ticketbox.data.repository.MerchantRepository
import com.ticketbox.data.repository.RecurringRepository
import com.ticketbox.data.repository.ReportsRepository
import com.ticketbox.data.repository.RuleRepository
import com.ticketbox.security.SecureTokenStore

class AppContainer(context: Context) {
    private val appContext = context.applicationContext
    val settingsStore = LocalSettingsStore(appContext)
    val tokenStore = SecureTokenStore(appContext)
    private val database = AppDatabase.getDatabase(appContext)
    private val apiClient = ApiClient(appContext)
    private val apiServiceProvider = ApiServiceProvider(apiClient, settingsStore, tokenStore)
    private val ledgerSessionCoordinator = LocalLedgerSessionCoordinator(
        settingsStore = settingsStore,
        tokenStore = tokenStore,
        expenseDao = database.expenseDao(),
    )

    val expenseRepository = ExpenseRepository(
        expenseDao = database.expenseDao(),
        apiClient = apiClient,
        settingsStore = settingsStore,
        tokenStore = tokenStore,
        apiProvider = apiServiceProvider,
        sessionCoordinator = ledgerSessionCoordinator,
    )

    val ledgerRepository = LedgerRepository(
        apiClient = apiClient,
        settingsStore = settingsStore,
        tokenStore = tokenStore,
        expenseDao = database.expenseDao(),
        apiProvider = apiServiceProvider,
        sessionCoordinator = ledgerSessionCoordinator,
    )

    val recurringRepository = RecurringRepository(
        apiClient = apiClient,
        settingsStore = settingsStore,
        tokenStore = tokenStore,
        apiProvider = apiServiceProvider,
    )

    val budgetRepository = BudgetRepository(
        apiClient = apiClient,
        settingsStore = settingsStore,
        tokenStore = tokenStore,
        apiProvider = apiServiceProvider,
    )

    val incomePlanRepository = IncomePlanRepository(
        apiClient = apiClient,
        settingsStore = settingsStore,
        tokenStore = tokenStore,
        apiProvider = apiServiceProvider,
    )

    val reportsRepository = ReportsRepository(
        apiClient = apiClient,
        settingsStore = settingsStore,
        tokenStore = tokenStore,
        apiProvider = apiServiceProvider,
    )

    val ruleRepository = RuleRepository(
        apiClient = apiClient,
        settingsStore = settingsStore,
        tokenStore = tokenStore,
        apiProvider = apiServiceProvider,
        onConfirmedChanged = { expenseRepository.syncConfirmed() },
    )

    val merchantRepository = MerchantRepository(
        apiClient = apiClient,
        settingsStore = settingsStore,
        tokenStore = tokenStore,
        apiProvider = apiServiceProvider,
    )
}
