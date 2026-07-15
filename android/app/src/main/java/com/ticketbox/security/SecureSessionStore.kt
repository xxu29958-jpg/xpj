package com.ticketbox.security

import android.content.Context
import android.util.Base64
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.MutablePreferences
import androidx.datastore.preferences.core.Preferences
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import java.security.SecureRandom
import java.security.MessageDigest
import java.time.Instant
import java.util.UUID
import java.util.concurrent.atomic.AtomicReference

/** Android Keystore-encrypted source for session and in-flight enrollment state. */
class SecureSessionStore private constructor(
    private val appContext: Context,
    private val persistence: SecureSessionPersistence,
) : LocalSessionStore {
    constructor(context: Context) : this(
        appContext = context.applicationContext,
        persistence = SecureSessionPersistenceProvider.get(context.applicationContext),
    )

    internal constructor(context: Context, dataStore: DataStore<Preferences>) : this(
        appContext = context.applicationContext,
        persistence = SecureSessionPersistence(dataStore),
    )

    override val sessionRefresh: SessionRefreshStore = SecureSessionRefreshStore(persistence)

    override fun hasPersistedSessionState(): Boolean = persistence.current.hasStateMarker

    override fun currentSession(): LocalSessionRecord? = persistence.current.session

    override fun observeSession(): Flow<LocalSessionRecord?> = persistence.sessions

    override fun pendingDeviceEnrollment(): PendingDeviceEnrollment? =
        persistence.current.pendingDeviceEnrollment

    override suspend fun beginOrReuseDeviceEnrollment(
        intent: DeviceEnrollmentIntent,
    ): PendingDeviceEnrollment {
        validateEnrollmentIntent(intent)
        return persistence.update { persisted ->
            persisted.pendingDeviceEnrollment
                ?.takeIf { it.intent.hasSameAuthoritySource(intent) }
                ?: PendingDeviceEnrollment(
                    attemptId = UUID.randomUUID().toString(),
                    intent = intent,
                    attemptSecret = newAttemptSecret(),
                    createdAt = Instant.now().toString(),
                ).also { writeDeviceEnrollment(it) }
        }
    }

    override suspend fun establishSession(
        record: LocalSessionRecord,
        completedEnrollmentAttemptId: String?,
    ) {
        validateSessionRecord(record)
        persistence.update { persisted ->
            if (completedEnrollmentAttemptId != null) {
                check(persisted.pendingDeviceEnrollment?.attemptId == completedEnrollmentAttemptId) {
                    "The completed enrollment attempt is no longer current."
                }
            }
            writeSession(record)
            clearSessionRefresh()
            if (completedEnrollmentAttemptId != null) clearDeviceEnrollment()
            Unit
        }
    }

    override suspend fun updateBindingIfCurrent(update: LocalSessionBindingUpdate): Boolean =
        persistence.update { persisted ->
            val current = persisted.session ?: return@update false
            if (current.version != update.expectedVersion) return@update false
            val replacement = LocalSessionRecord(
                sessionGeneration = current.sessionGeneration,
                bindingRevision = update.bindingRevision,
                serverId = update.serverId,
                dataGeneration = update.dataGeneration,
                serverUrl = update.serverUrl,
                credential = update.replacementCredential ?: current.credential,
                identity = update.identity,
            )
            validateSessionRecord(replacement)
            writeSession(replacement)
            if (update.replacementCredential != null) clearSessionRefresh()
            true
        }

    override suspend fun clearSession() {
        persistence.update {
            clear()
            Unit
        }
    }

    internal fun legacyCredentialOrNull(): StoredSessionToken? =
        readLegacySessionToken(appContext)

    internal fun retireLegacyCredential() {
        clearLegacySessionToken(appContext)
    }

}

private object SecureSessionPersistenceProvider {
    @Volatile
    private var instance: SecureSessionPersistence? = null

    fun get(context: Context): SecureSessionPersistence =
        instance ?: synchronized(this) {
            instance ?: SecureSessionPersistence(
                secureSessionDataStore(context.applicationContext),
            ).also { instance = it }
        }
}

private class SecureSessionRefreshStore(
    private val persistence: SecureSessionPersistence,
) : SessionRefreshStore {
    override fun pending(): PendingSessionRefresh? =
        persistence.current.pendingSessionRefresh

    override suspend fun beginOrReuse(
        expectedSessionGeneration: String,
        expectedToken: String,
    ): PendingSessionRefresh? = persistence.update { persisted ->
        val current = persisted.session ?: return@update null
        if (current.sessionGeneration != expectedSessionGeneration ||
            current.credential.token != expectedToken
        ) {
            return@update null
        }
        val fingerprint = sessionTokenFingerprint(expectedToken)
        persisted.pendingSessionRefresh
            ?.takeIf { it.matches(expectedSessionGeneration, fingerprint) }
            ?: PendingSessionRefresh(
                attemptId = UUID.randomUUID().toString(),
                attemptSecret = newAttemptSecret(),
                sessionGeneration = expectedSessionGeneration,
                sourceTokenFingerprint = fingerprint,
                createdAt = Instant.now().toString(),
            ).also { writeSessionRefresh(it) }
    }

    override suspend fun resume(
        expectedSessionGeneration: String,
        expectedToken: String,
    ): PendingSessionRefresh? {
        val persisted = persistence.current
        val current = persisted.session ?: return null
        if (current.sessionGeneration != expectedSessionGeneration ||
            current.credential.token != expectedToken
        ) {
            return null
        }
        val fingerprint = sessionTokenFingerprint(expectedToken)
        return persisted.pendingSessionRefresh
            ?.takeIf { it.matches(expectedSessionGeneration, fingerprint) }
    }

    override suspend fun completeIfCurrent(
        expectedSessionGeneration: String,
        expectedToken: String,
        refreshAttemptId: String,
        replacement: StoredSessionToken,
    ): Boolean = persistence.update { persisted ->
        val current = persisted.session ?: return@update false
        val attempt = persisted.pendingSessionRefresh ?: return@update false
        if (current.sessionGeneration != expectedSessionGeneration ||
            current.credential.token != expectedToken ||
            attempt.attemptId != refreshAttemptId ||
            !attempt.matches(
                expectedSessionGeneration,
                sessionTokenFingerprint(expectedToken),
            )
        ) {
            return@update false
        }
        val updated = current.copy(credential = replacement)
        validateSessionRecord(updated)
        writeSession(updated)
        clearSessionRefresh()
        true
    }
}

private fun PendingSessionRefresh.matches(
    expectedSessionGeneration: String,
    expectedTokenFingerprint: String,
): Boolean =
    sessionGeneration == expectedSessionGeneration &&
        sourceTokenFingerprint == expectedTokenFingerprint

private fun newAttemptSecret(): String {
    val bytes = ByteArray(32).also(SecureRandom()::nextBytes)
    return Base64.encodeToString(
        bytes,
        Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING,
    )
}

private fun sessionTokenFingerprint(token: String): String =
    MessageDigest.getInstance("SHA-256")
        .digest(token.toByteArray(Charsets.UTF_8))
        .joinToString(separator = "") { byte -> "%02x".format(byte) }

private fun validateEnrollmentIntent(intent: DeviceEnrollmentIntent) {
    require(intent.serverUrl.isNotBlank()) { "Enrollment server origin is required." }
    require(intent.deviceName.isNotBlank()) { "Enrollment device name is required." }
    when (intent) {
        is DeviceEnrollmentIntent.Pairing -> {
            require(intent.pairingCode.isNotBlank()) { "Pairing code is required." }
        }
        is DeviceEnrollmentIntent.Invitation -> {
            require(intent.inviteToken.isNotBlank()) { "Invitation token is required." }
            require(intent.accountName.isNotBlank()) { "Invitation account name is required." }
        }
    }
}

private fun validateSessionRecord(record: LocalSessionRecord) {
    require(record.sessionGeneration.isNotBlank()) { "Session generation is required." }
    require(record.bindingRevision.isNotBlank()) { "Binding revision is required." }
    require(record.serverUrl.isNotBlank()) { "Session server origin is required." }
    require(record.credential.token.isNotBlank()) { "Session token is required." }
    require(record.identity.ledgerId.isNotBlank()) { "Selected ledger is required." }
}

private class SecureSessionPersistence(
    private val dataStore: DataStore<Preferences>,
) {
    private val updateLease = Mutex()
    private val snapshot = AtomicReference(
        runBlocking(Dispatchers.IO) { dataStore.data.first().toSessionStoreSnapshot() },
    )
    private val sessionFlow = MutableStateFlow(snapshot.get().session)

    val sessions: Flow<LocalSessionRecord?>
        get() = sessionFlow

    val current: SessionStoreSnapshot
        get() = snapshot.get()

    suspend fun <T> update(
        transform: MutablePreferences.(SessionStoreSnapshot) -> T,
    ): T = updateLease.withLock {
        withContext(Dispatchers.IO) {
            var result: T? = null
            val committed = dataStore.updateData { persisted ->
                val mutable = persisted.toMutablePreferences()
                result = mutable.transform(persisted.toSessionStoreSnapshot())
                mutable
            }
            val committedSnapshot = committed.toSessionStoreSnapshot()
            snapshot.set(committedSnapshot)
            sessionFlow.value = committedSnapshot.session
            @Suppress("UNCHECKED_CAST")
            result as T
        }
    }
}
