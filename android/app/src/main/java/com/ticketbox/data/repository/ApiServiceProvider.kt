package com.ticketbox.data.repository

import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.security.SessionTokenStore

/**
 * Owns the bound ledger ApiService cache shared by repositories.
 *
 * The cached service reads the token lazily for every request, so token
 * rotation after ledger switching does not require rebuilding Retrofit.
 */
class ApiServiceProvider(
    private val apiClient: ApiServiceFactory,
    private val settingsStore: TicketboxSettingsStore,
    private val tokenStore: SessionTokenStore,
) {
    private val lock = Any()
    private var cachedServerUrl: String? = null
    private var cachedApi: ApiService? = null

    fun current(): ApiService {
        val serverUrl = requireServerUrl(settingsStore.serverUrl())
        val cached = cachedApi
        if (cached != null && cachedServerUrl == serverUrl) {
            return cached
        }

        return synchronized(lock) {
            val lockedCached = cachedApi
            if (lockedCached != null && cachedServerUrl == serverUrl) {
                lockedCached
            } else {
                apiClient.create(serverUrl) { tokenStore.getToken() }
                    .also { service ->
                        cachedServerUrl = serverUrl
                        cachedApi = service
                    }
            }
        }
    }

    fun temporary(serverUrl: String, tokenOverride: String? = null): ApiService {
        val cleanServerUrl = requireServerUrl(serverUrl)
        return apiClient.create(cleanServerUrl) { tokenOverride ?: tokenStore.getToken() }
    }

    fun clear() {
        synchronized(lock) {
            cachedServerUrl = null
            cachedApi = null
        }
    }

    private fun requireServerUrl(value: String?): String {
        val serverUrl = value?.trim()?.trimEnd('/')
        require(!serverUrl.isNullOrBlank()) { "账本地址未绑定" }
        return serverUrl
    }
}
