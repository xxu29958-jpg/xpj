package com.ticketbox.security

import kotlinx.coroutines.flow.Flow

data class LocalSessionIdentity(
    val accountPublicId: String? = null,
    val devicePublicId: String? = null,
    val accountName: String,
    val ledgerId: String,
    val ledgerName: String,
    val deviceName: String,
    val role: String,
    val boundAt: String,
)

data class LocalSessionVersion(
    val sessionGeneration: String,
    val bindingRevision: String,
)

data class LocalSessionRecord(
    val sessionGeneration: String,
    val bindingRevision: String,
    val serverId: String? = null,
    val dataGeneration: String? = null,
    val serverUrl: String,
    val credential: StoredSessionToken,
    val identity: LocalSessionIdentity,
) {
    val version: LocalSessionVersion
        get() = LocalSessionVersion(sessionGeneration, bindingRevision)
}

data class LocalSessionBindingUpdate(
    val expectedVersion: LocalSessionVersion,
    val bindingRevision: String,
    val serverId: String?,
    val dataGeneration: String?,
    val serverUrl: String,
    val identity: LocalSessionIdentity,
    val replacementCredential: StoredSessionToken? = null,
)

/**
 * Single durable source for this installation's authenticated session.
 *
 * Session generation changes only when the account/device session changes.
 * Binding revision changes when the selected server/ledger changes. Credential
 * rotation changes neither, so an in-flight request stays in the same logical
 * binding while its bearer token is refreshed.
 */
interface LocalSessionStore {
    val sessionRefresh: SessionRefreshStore

    fun hasPersistedSessionState(): Boolean

    fun currentSession(): LocalSessionRecord?

    fun observeSession(): Flow<LocalSessionRecord?>

    suspend fun establishSession(
        record: LocalSessionRecord,
        completedEnrollmentAttemptId: String? = null,
    )

    suspend fun updateBindingIfCurrent(update: LocalSessionBindingUpdate): Boolean

    fun pendingDeviceEnrollment(): PendingDeviceEnrollment?

    suspend fun beginOrReuseDeviceEnrollment(
        intent: DeviceEnrollmentIntent,
    ): PendingDeviceEnrollment

    suspend fun clearSession()
}

sealed interface DeviceEnrollmentIntent {
    val serverUrl: String
    val deviceName: String

    fun hasSameAuthoritySource(other: DeviceEnrollmentIntent): Boolean = when {
        this is Pairing && other is Pairing ->
            serverUrl == other.serverUrl && pairingCode == other.pairingCode
        this is Invitation && other is Invitation ->
            serverUrl == other.serverUrl && inviteToken == other.inviteToken
        else -> false
    }

    data class Pairing(
        override val serverUrl: String,
        val pairingCode: String,
        override val deviceName: String,
    ) : DeviceEnrollmentIntent

    data class Invitation(
        override val serverUrl: String,
        val inviteToken: String,
        val accountName: String,
        override val deviceName: String,
    ) : DeviceEnrollmentIntent
}

data class PendingDeviceEnrollment(
    val attemptId: String,
    val intent: DeviceEnrollmentIntent,
    val attemptSecret: String,
    val createdAt: String,
) {
    val serverUrl: String
        get() = intent.serverUrl
}

data class PendingSessionRefresh(
    val attemptId: String,
    val attemptSecret: String,
    val sessionGeneration: String,
    val sourceTokenFingerprint: String,
    val createdAt: String,
)

/** Durable sub-port for the one in-flight refresh transaction of a session. */
interface SessionRefreshStore {
    fun pending(): PendingSessionRefresh?

    suspend fun beginOrReuse(
        expectedSessionGeneration: String,
        expectedToken: String,
    ): PendingSessionRefresh?

    suspend fun resume(
        expectedSessionGeneration: String,
        expectedToken: String,
    ): PendingSessionRefresh?

    suspend fun completeIfCurrent(
        expectedSessionGeneration: String,
        expectedToken: String,
        refreshAttemptId: String,
        replacement: StoredSessionToken,
    ): Boolean
}

class SessionCredentialAdapter(
    private val sessionStore: LocalSessionStore,
) : SessionCredentialRotator {
    override fun getToken(): String? = sessionStore.currentSession()?.credential?.token

    override fun getSessionToken(): StoredSessionToken? =
        sessionStore.currentSession()?.credential

    override fun currentLedgerId(): String? =
        sessionStore.currentSession()?.identity?.ledgerId

    override fun sessionGeneration(): String? =
        sessionStore.currentSession()?.sessionGeneration

    override fun requestAuthSnapshot(): RequestAuthSnapshot? {
        val session = sessionStore.currentSession() ?: return null
        return RequestAuthSnapshot(
            credential = session.credential,
            ledgerId = session.identity.ledgerId,
            sessionGeneration = session.sessionGeneration,
            bindingRevision = session.bindingRevision,
        )
    }

    override suspend fun beginOrReuseSessionRefresh(
        expectedSessionGeneration: String,
        expectedToken: String,
    ): PendingSessionRefresh? = sessionStore.sessionRefresh.beginOrReuse(
        expectedSessionGeneration = expectedSessionGeneration,
        expectedToken = expectedToken,
    )

    override suspend fun resumeSessionRefresh(
        expectedSessionGeneration: String,
        expectedToken: String,
    ): PendingSessionRefresh? = sessionStore.sessionRefresh.resume(
        expectedSessionGeneration = expectedSessionGeneration,
        expectedToken = expectedToken,
    )

    override suspend fun completeSessionRefreshIfCurrent(
        expectedSessionGeneration: String,
        expectedToken: String,
        refreshAttemptId: String,
        replacement: StoredSessionToken,
    ): Boolean = sessionStore.sessionRefresh.completeIfCurrent(
        expectedSessionGeneration = expectedSessionGeneration,
        expectedToken = expectedToken,
        refreshAttemptId = refreshAttemptId,
        replacement = replacement,
    )
}
