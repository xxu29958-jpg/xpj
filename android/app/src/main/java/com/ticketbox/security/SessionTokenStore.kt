package com.ticketbox.security

data class StoredSessionToken(
    val token: String,
    val expiresAt: String? = null,
    val softRefreshAfter: String? = null,
)

interface SessionTokenStore {
    fun saveToken(token: String)

    fun saveToken(token: String, expiresAt: String?, softRefreshAfter: String?) {
        saveToken(token)
    }

    fun getToken(): String?

    fun getSessionToken(): StoredSessionToken? =
        getToken()?.takeIf { it.isNotBlank() }?.let { token ->
            StoredSessionToken(token = token)
        }

    fun clear()
}
