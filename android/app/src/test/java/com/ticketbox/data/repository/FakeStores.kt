package com.ticketbox.data.repository

import com.ticketbox.data.local.PersistedLedgerIdentity
import com.ticketbox.data.local.PersistedSessionProjection
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.local.ExpenseDao
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.domain.model.BackgroundCropMode
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.domain.model.NotificationPreferences
import com.ticketbox.security.LocalSessionBindingUpdate
import com.ticketbox.security.DeviceEnrollmentIntent
import com.ticketbox.security.LocalSessionIdentity
import com.ticketbox.security.LocalSessionRecord
import com.ticketbox.security.LocalSessionStore
import com.ticketbox.security.PendingDeviceEnrollment
import com.ticketbox.security.PendingSessionRefresh
import com.ticketbox.security.SessionCredentialProvider
import com.ticketbox.security.SessionCredentialAdapter
import com.ticketbox.security.SessionRefreshStore
import com.ticketbox.security.StoredSessionToken
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import java.security.SecureRandom
import java.security.MessageDigest
import java.time.Instant
import java.util.Base64
import java.util.UUID

private fun stableTestIdentityId(name: String): String =
    UUID.nameUUIDFromBytes("ticketbox-test:$name".toByteArray(Charsets.UTF_8)).toString()

internal val TEST_SERVER_ID = stableTestIdentityId("primary-server")
internal val TEST_DATA_GENERATION = stableTestIdentityId("primary-data-generation")
internal val TEST_ACCOUNT_PUBLIC_ID = stableTestIdentityId("primary-account")
internal val TEST_DEVICE_PUBLIC_ID = stableTestIdentityId("primary-device")
private val TEST_OTHER_SERVER_ID = stableTestIdentityId("other-server")
private val TEST_OTHER_DATA_GENERATION = stableTestIdentityId("other-data-generation")
private val TEST_OTHER_ACCOUNT_PUBLIC_ID = stableTestIdentityId("other-account")
private val TEST_OTHER_DEVICE_PUBLIC_ID = stableTestIdentityId("other-device")

internal fun boundSettingsStore(
    role: String = "owner",
    events: MutableList<String> = mutableListOf(),
): FakeTicketboxSettingsStore =
    FakeTicketboxSettingsStore(events).apply {
        saveServerUrl("https://api.example.com")
        saveIdentity(
            PersistedLedgerIdentity(
                accountName = "我",
                ledgerId = "owner",
                ledgerName = "我的小票夹",
                deviceName = "Pixel",
                role = role,
                boundAt = "2026-05-01T00:00:00Z",
            )
        )
    }

internal class FakeTicketboxSettingsStore(
    private val events: MutableList<String> = mutableListOf(),
) : TicketboxSettingsStore {
    private val backgroundSettings = MutableStateFlow(BackgroundSettings())
    override val backgroundSettingsFlow: Flow<BackgroundSettings> = backgroundSettings
    private var serverUrl: String? = null
    private var accountName: String? = null
    private val ledgerIdFlow = MutableStateFlow<String?>(null)
    private var ledgerName: String? = null
    private var availableLedgersJson: String? = null
    private var deviceName: String? = null
    private var role: String? = null
    private var boundAt: String? = null
    private val lastConfirmedSyncAtByLedger = mutableMapOf<String, String>()
    private var lastUploadAt: String? = null
    private var monthlyBudgetCents: Long? = null
    private var notificationPreferences: NotificationPreferences = NotificationPreferences()
    private var appSkinKey: String? = null
    var onSaveIdentity: (() -> Unit)? = null
    var backgroundWriteFailure: Throwable? = null
    var sessionProjectionWriteFailure: Throwable? = null

    fun serverUrl(): String? = serverUrl

    override fun appSkinKey(): String? = appSkinKey

    override fun monthlyBudgetCents(): Long? = monthlyBudgetCents

    override fun saveMonthlyBudgetCents(amountCents: Long?) {
        monthlyBudgetCents = amountCents
    }

    override fun notificationPreferences(): NotificationPreferences = notificationPreferences

    override fun saveNotificationPreferences(preferences: NotificationPreferences) {
        notificationPreferences = preferences
    }

    override suspend fun saveBackgroundSettings(settings: BackgroundSettings) {
        backgroundWriteFailure?.let { throw it }
        backgroundSettings.value = settings
    }

    override suspend fun saveBackgroundImagePath(path: String) {
        saveBackgroundSettings(BackgroundSettings().withCustomImage(path.trim()))
    }

    override suspend fun clearBackgroundImage() {
        saveBackgroundSettings(backgroundSettings.value.withoutBackground())
    }

    override suspend fun setBackgroundCropMode(mode: BackgroundCropMode) {
        saveBackgroundSettings(backgroundSettings.value.copy(cropMode = mode))
    }

    override suspend fun setImmersionMode(mode: ImmersionMode) {
        saveBackgroundSettings(backgroundSettings.value.copy(immersionMode = mode))
    }

    override suspend fun setParallaxEnabled(enabled: Boolean) {
        saveBackgroundSettings(backgroundSettings.value.copy(enableParallax = enabled))
    }

    override suspend fun setReduceMotion(enabled: Boolean) {
        saveBackgroundSettings(
            backgroundSettings.value.copy(
                reduceMotion = enabled,
                enableParallax = backgroundSettings.value.enableParallax && !enabled,
            ),
        )
    }

    override fun lastConfirmedSyncAt(): String? =
        lastConfirmedSyncAtByLedger[activeLedgerId() ?: "legacy"]

    fun accountName(): String? = accountName

    fun ledgerName(): String? = ledgerName

    fun activeLedgerId(): String? = ledgerIdFlow.value

    fun activeLedgerName(): String? = ledgerName

    override fun availableLedgersJson(): String? = availableLedgersJson

    fun observeActiveLedgerId(): Flow<String?> = ledgerIdFlow

    fun saveActiveLedger(ledgerId: String, ledgerName: String) {
        events += "saveActiveLedger"
        ledgerIdFlow.value = ledgerId
        this.ledgerName = ledgerName
    }

    override fun saveAvailableLedgersJson(json: String?) {
        availableLedgersJson = json
    }

    fun deviceName(): String? = deviceName

    fun role(): String? = role

    fun boundAt(): String? = boundAt

    fun saveIdentity(identity: PersistedLedgerIdentity) {
        events += "saveIdentity"
        accountName = identity.accountName
        ledgerIdFlow.value = identity.ledgerId
        ledgerName = identity.ledgerName
        deviceName = identity.deviceName
        role = identity.role
        boundAt = identity.boundAt
        onSaveIdentity?.invoke()
    }

    fun saveSessionProjection(projection: PersistedSessionProjection) {
        sessionProjectionWriteFailure?.let { throw it }
        saveServerUrl(projection.serverUrl)
        saveIdentity(projection.identity)
    }

    override fun saveLastConfirmedSyncAt(value: String) {
        saveLastConfirmedSyncAtForLedger(activeLedgerId() ?: "legacy", value)
    }

    override fun saveLastConfirmedSyncAtForLedger(ledgerId: String, value: String) {
        lastConfirmedSyncAtByLedger[ledgerId] = value
    }

    override fun clearLastConfirmedSyncAt() {
        lastConfirmedSyncAtByLedger.remove(activeLedgerId() ?: "legacy")
    }

    override fun clearLastConfirmedSyncAtForLedger(ledgerId: String) {
        events += "clearLastConfirmedSyncAtForLedger:$ledgerId"
        lastConfirmedSyncAtByLedger.remove(ledgerId)
    }

    override fun clearLedgerScopedRuntimeState() {
        events += "clearLedgerScopedRuntimeState"
        lastConfirmedSyncAtByLedger.clear()
        lastUploadAt = null
    }

    override fun lastUploadAt(): String? = lastUploadAt

    override fun saveLastUploadAt(value: String) {
        lastUploadAt = value
    }

    override fun saveAppSkinKey(skinKey: String) {
        appSkinKey = skinKey
    }

    override fun currencyCodeKey(): String? = null

    override fun saveCurrencyCodeKey(currencyKey: String) = Unit

    override fun observeCurrencyCodeKey(): Flow<String?> = MutableStateFlow(null)

    fun saveServerUrl(serverUrl: String) {
        events += "saveServerUrl"
        this.serverUrl = serverUrl.trim().trimEnd('/')
    }

    fun isBound(): Boolean = !serverUrl.isNullOrBlank()

    override fun markUnlocked() = Unit

    override fun markBackgrounded() = Unit

    override fun requiresUnlock(): Boolean = false

    override fun clear() {
        serverUrl = null
        accountName = null
        ledgerIdFlow.value = null
        ledgerName = null
        deviceName = null
        role = null
        boundAt = null
        lastConfirmedSyncAtByLedger.clear()
        lastUploadAt = null
    }
}

internal class InMemoryLocalSessionStore(
    initial: LocalSessionRecord? = null,
) : LocalSessionStore {
    private val lock = Any()
    private var hasStateMarker = initial != null
    private var session = initial
    private var pendingEnrollment: PendingDeviceEnrollment? = null
    private var pendingRefresh: PendingSessionRefresh? = null
    private val sessionFlow = MutableStateFlow(initial)
    override val sessionRefresh: SessionRefreshStore = InMemorySessionRefreshStore()

    override fun hasPersistedSessionState(): Boolean = synchronized(lock) { hasStateMarker }

    override fun currentSession(): LocalSessionRecord? = synchronized(lock) { session }

    override fun observeSession(): Flow<LocalSessionRecord?> = sessionFlow

    override fun pendingDeviceEnrollment(): PendingDeviceEnrollment? =
        synchronized(lock) { pendingEnrollment }

    override suspend fun beginOrReuseDeviceEnrollment(
        intent: DeviceEnrollmentIntent,
    ): PendingDeviceEnrollment = synchronized(lock) {
        pendingEnrollment
            ?.takeIf { it.intent.hasSameAuthoritySource(intent) }
            ?: PendingDeviceEnrollment(
                attemptId = UUID.randomUUID().toString(),
                intent = intent,
                attemptSecret = Base64.getUrlEncoder().withoutPadding().encodeToString(
                    ByteArray(32).also(SecureRandom()::nextBytes),
                ),
                createdAt = Instant.now().toString(),
            ).also {
                pendingEnrollment = it
                hasStateMarker = true
            }
    }

    override suspend fun establishSession(
        record: LocalSessionRecord,
        completedEnrollmentAttemptId: String?,
    ) {
        synchronized(lock) {
            if (completedEnrollmentAttemptId != null) {
                check(pendingEnrollment?.attemptId == completedEnrollmentAttemptId)
                pendingEnrollment = null
            }
            pendingRefresh = null
            replaceForFixture(record)
        }
    }

    override suspend fun updateBindingIfCurrent(update: LocalSessionBindingUpdate): Boolean =
        synchronized(lock) {
            val current = session ?: return@synchronized false
            if (current.version != update.expectedVersion) return@synchronized false
            session = current.copy(
                bindingRevision = update.bindingRevision,
                serverId = update.serverId,
                dataGeneration = update.dataGeneration,
                serverUrl = update.serverUrl,
                credential = update.replacementCredential ?: current.credential,
                identity = update.identity,
            )
            if (update.replacementCredential != null) pendingRefresh = null
            sessionFlow.value = session
            true
        }

    override suspend fun clearSession() {
        clearForFixture()
    }

    internal fun replaceForFixture(record: LocalSessionRecord) = synchronized(lock) {
        hasStateMarker = true
        session = record
        sessionFlow.value = record
    }

    internal fun clearForFixture() = synchronized(lock) {
        hasStateMarker = false
        session = null
        pendingEnrollment = null
        pendingRefresh = null
        sessionFlow.value = null
    }

    private inner class InMemorySessionRefreshStore : SessionRefreshStore {
        override fun pending(): PendingSessionRefresh? =
            synchronized(lock) { pendingRefresh }

        override suspend fun beginOrReuse(
            expectedSessionGeneration: String,
            expectedToken: String,
        ): PendingSessionRefresh? = synchronized(lock) {
            val current = session ?: return@synchronized null
            if (current.sessionGeneration != expectedSessionGeneration ||
                current.credential.token != expectedToken
            ) {
                return@synchronized null
            }
            val fingerprint = testTokenFingerprint(expectedToken)
            pendingRefresh
                ?.takeIf {
                    it.sessionGeneration == expectedSessionGeneration &&
                        it.sourceTokenFingerprint == fingerprint
                }
                ?: PendingSessionRefresh(
                    attemptId = UUID.randomUUID().toString(),
                    attemptSecret = Base64.getUrlEncoder().withoutPadding().encodeToString(
                        ByteArray(32).also(SecureRandom()::nextBytes),
                    ),
                    sessionGeneration = expectedSessionGeneration,
                    sourceTokenFingerprint = fingerprint,
                    createdAt = Instant.now().toString(),
                ).also {
                    pendingRefresh = it
                    hasStateMarker = true
                }
        }

        override suspend fun completeIfCurrent(
            expectedSessionGeneration: String,
            expectedToken: String,
            refreshAttemptId: String,
            replacement: StoredSessionToken,
        ): Boolean = synchronized(lock) {
            val current = session ?: return@synchronized false
            val attempt = pendingRefresh ?: return@synchronized false
            if (current.sessionGeneration != expectedSessionGeneration ||
                current.credential.token != expectedToken ||
                attempt.attemptId != refreshAttemptId ||
                attempt.sourceTokenFingerprint != testTokenFingerprint(expectedToken)
            ) {
                return@synchronized false
            }
            session = current.copy(credential = replacement)
            pendingRefresh = null
            sessionFlow.value = session
            true
        }
    }
}

private fun testTokenFingerprint(token: String): String =
    MessageDigest.getInstance("SHA-256")
        .digest(token.toByteArray(Charsets.UTF_8))
        .joinToString(separator = "") { byte -> "%02x".format(byte) }

internal class TestSessionFixture(
    private val events: MutableList<String> = mutableListOf(),
    private val serverUrl: String = "https://api.example.com",
    identity: LocalSessionIdentity = LocalSessionIdentity(
        accountPublicId = TEST_ACCOUNT_PUBLIC_ID,
        devicePublicId = TEST_DEVICE_PUBLIC_ID,
        accountName = "我",
        ledgerId = "owner",
        ledgerName = "我的小票夹",
        deviceName = "Pixel",
        role = "owner",
        boundAt = "2026-05-01T00:00:00Z",
    ),
) : SessionCredentialProvider {
    private val identity = identity.copy(
        accountPublicId = identity.accountPublicId ?: TEST_ACCOUNT_PUBLIC_ID,
        devicePublicId = identity.devicePublicId ?: TEST_DEVICE_PUBLIC_ID,
    )
    internal val sessionStore = InMemoryLocalSessionStore()
    private val credentials = SessionCredentialAdapter(sessionStore)
    private var nextGeneration = 1
    private var nextBindingRevision = 1

    fun saveToken(token: String) {
        events += "saveToken"
        val credential = StoredSessionToken(token)
        val current = sessionStore.currentSession()
        if (current == null) {
            sessionStore.replaceForFixture(
                LocalSessionRecord(
                    sessionGeneration = newSessionGeneration(),
                    bindingRevision = newBindingRevision(),
                    serverId = TEST_SERVER_ID,
                    dataGeneration = TEST_DATA_GENERATION,
                    serverUrl = serverUrl,
                    credential = credential,
                    identity = identity,
                ),
            )
        } else {
            sessionStore.replaceForFixture(current.copy(credential = credential))
        }
    }

    override fun getToken(): String? = credentials.getToken()

    override fun getSessionToken(): StoredSessionToken? = credentials.getSessionToken()

    override fun sessionGeneration(): String? = credentials.sessionGeneration()

    fun clear() {
        sessionStore.clearForFixture()
    }

    fun switchLedgerForFixture(
        ledgerId: String,
        ledgerName: String,
        role: String = "owner",
    ) {
        val current = requireNotNull(sessionStore.currentSession())
        sessionStore.replaceForFixture(
            current.copy(
                bindingRevision = newBindingRevision(),
                identity = current.identity.copy(
                    ledgerId = ledgerId,
                    ledgerName = ledgerName,
                    role = role,
                ),
            ),
        )
    }

    fun rebindToDifferentServerForFixture(
        serverUrl: String,
        token: String,
    ) {
        val current = requireNotNull(sessionStore.currentSession())
        sessionStore.replaceForFixture(
            current.copy(
                sessionGeneration = newSessionGeneration(),
                bindingRevision = newBindingRevision(),
                serverId = TEST_OTHER_SERVER_ID,
                dataGeneration = TEST_OTHER_DATA_GENERATION,
                serverUrl = serverUrl,
                credential = StoredSessionToken(token),
                identity = current.identity.copy(
                    accountPublicId = TEST_OTHER_ACCOUNT_PUBLIC_ID,
                    devicePublicId = TEST_OTHER_DEVICE_PUBLIC_ID,
                ),
            ),
        )
    }

    fun acceptInvitationForFixture(
        ledgerId: String,
        ledgerName: String,
        role: String,
        accountName: String,
        deviceName: String,
    ) {
        val current = requireNotNull(sessionStore.currentSession())
        sessionStore.replaceForFixture(
            current.copy(
                sessionGeneration = newSessionGeneration(),
                bindingRevision = newBindingRevision(),
                identity = current.identity.copy(
                    accountName = accountName,
                    ledgerId = ledgerId,
                    ledgerName = ledgerName,
                    deviceName = deviceName,
                    role = role,
                ),
            ),
        )
    }

    fun rebindAsDifferentAccountForFixture(
        accountName: String,
        ledgerId: String,
        ledgerName: String,
        deviceName: String,
        token: String,
    ) {
        val current = requireNotNull(sessionStore.currentSession())
        sessionStore.replaceForFixture(
            current.copy(
                sessionGeneration = newSessionGeneration(),
                bindingRevision = newBindingRevision(),
                credential = StoredSessionToken(token),
                identity = current.identity.copy(
                    accountPublicId = TEST_OTHER_ACCOUNT_PUBLIC_ID,
                    devicePublicId = TEST_OTHER_DEVICE_PUBLIC_ID,
                    accountName = accountName,
                    ledgerId = ledgerId,
                    ledgerName = ledgerName,
                    deviceName = deviceName,
                ),
            ),
        )
    }

    private fun newSessionGeneration(): String = "test-session-${nextGeneration++}"

    private fun newBindingRevision(): String = "test-binding-${nextBindingRevision++}"
}

internal fun testApiServiceProvider(
    apiClient: ApiServiceFactory,
    tokenStore: TestSessionFixture,
): ApiServiceProvider {
    return ApiServiceProvider(
        apiClient = apiClient,
        sessionStore = tokenStore.sessionStore,
        credentials = SessionCredentialAdapter(tokenStore.sessionStore),
    )
}

internal fun testServerSessionBinding(
    apiClient: ApiServiceFactory,
    settingsStore: TicketboxSettingsStore,
    tokenStore: TestSessionFixture,
    apiProvider: ApiServiceProvider? = null,
): ServerSessionBinding {
    return ServerSessionBinding(
        apiClient = apiClient,
        settingsStore = settingsStore,
        sessionStore = tokenStore.sessionStore,
        credentials = SessionCredentialAdapter(tokenStore.sessionStore),
        apiProvider = apiProvider ?: testApiServiceProvider(apiClient, tokenStore),
    )
}

internal fun testLedgerRepository(
    apiClient: ApiServiceFactory,
    settingsStore: TicketboxSettingsStore,
    tokenStore: TestSessionFixture,
    expenseDao: ExpenseDao,
): LedgerRepository {
    return LedgerRepository(
        settingsStore = settingsStore,
        expenseDao = expenseDao,
        sessionStore = tokenStore.sessionStore,
        apiProvider = testApiServiceProvider(apiClient, tokenStore),
        sessionCoordinator = LocalLedgerSessionCoordinator(
            settingsStore = settingsStore,
            sessionStore = tokenStore.sessionStore,
            expenseDao = expenseDao,
        ),
    )
}
