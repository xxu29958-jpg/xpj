package com.ticketbox.security

data class StoredSessionToken(
    val token: String,
    val expiresAt: String? = null,
    val softRefreshAfter: String? = null,
)

data class RequestAuthSnapshot(
    val credential: StoredSessionToken,
    val ledgerId: String,
    val sessionGeneration: String,
    val bindingRevision: String,
) {
    val version: LocalSessionVersion
        get() = LocalSessionVersion(sessionGeneration, bindingRevision)
}

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
    /** Token and ledger selection captured from one immutable session record. */
    fun requestAuthSnapshot(): RequestAuthSnapshot?

    suspend fun beginOrReuseSessionRefresh(
        expectedSessionGeneration: String,
        expectedToken: String,
    ): PendingSessionRefresh?

    suspend fun resumeSessionRefresh(
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
