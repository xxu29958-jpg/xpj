package com.ticketbox.security

data class StoredSessionToken(
    val token: String,
    val expiresAt: String? = null,
    val softRefreshAfter: String? = null,
)

/** Read-only credential view used by HTTP clients and repositories. */
interface SessionCredentialProvider {
    fun getToken(): String?

    fun currentLedgerId(): String? = null

    fun getSessionToken(): StoredSessionToken? =
        getToken()?.takeIf { it.isNotBlank() }?.let(::StoredSessionToken)

    fun sessionGeneration(): String? = null
}

/** Credential rotation is narrower than replacing a complete local session. */
interface SessionCredentialRotator : SessionCredentialProvider {
    suspend fun beginOrReuseSessionRefresh(
        expectedSessionGeneration: String,
        expectedToken: String,
    ): PendingSessionRefresh?

    suspend fun completeSessionRefreshIfCurrent(
        expectedSessionGeneration: String,
        expectedToken: String,
        refreshAttemptId: String,
        replacement: StoredSessionToken,
    ): Boolean
}
