package com.ticketbox

import android.content.Context
import com.ticketbox.data.local.AppDatabase
import com.ticketbox.data.local.LocalSettingsStore
import com.ticketbox.data.remote.ApiClient
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.security.SecureTokenStore

class AppContainer(context: Context) {
    private val appContext = context.applicationContext
    val settingsStore = LocalSettingsStore(appContext)
    val tokenStore = SecureTokenStore(appContext)
    private val database = AppDatabase.getDatabase(appContext)
    private val apiClient = ApiClient()

    val expenseRepository = ExpenseRepository(
        expenseDao = database.expenseDao(),
        apiClient = apiClient,
        settingsStore = settingsStore,
        tokenStore = tokenStore,
    )
}
