package com.ticketbox.data.repository

import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.security.SessionTokenStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import java.lang.reflect.Proxy
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertSame

class ApiServiceProviderTest {
    @Test
    fun currentReusesServiceForSameServerUrlAndReadsLatestToken() {
        val settings = ProviderSettingsStore().apply { saveServerUrl("https://api.example.com") }
        val tokenStore = ProviderTokenStore().apply { saveToken("token-1") }
        val factory = RecordingApiFactory()
        val provider = ApiServiceProvider(factory, settings, tokenStore)

        val first = provider.current()
        val second = provider.current()

        assertSame(first, second)
        assertEquals(1, factory.creations.size)
        assertEquals("token-1", factory.creations.single().tokenProvider())

        tokenStore.saveToken("token-2")

        assertSame(first, provider.current())
        assertEquals(1, factory.creations.size)
        assertEquals("token-2", factory.creations.single().tokenProvider())
    }

    @Test
    fun currentRebuildsWhenServerUrlChanges() {
        val settings = ProviderSettingsStore().apply { saveServerUrl("https://api-a.example") }
        val tokenStore = ProviderTokenStore().apply { saveToken("session-token") }
        val factory = RecordingApiFactory()
        val provider = ApiServiceProvider(factory, settings, tokenStore)

        val first = provider.current()
        settings.saveServerUrl("https://api-b.example")
        val second = provider.current()

        assertFalse(first === second)
        assertEquals(listOf("https://api-a.example", "https://api-b.example"), factory.creations.map { it.baseUrl })
    }

    @Test
    fun temporaryServiceDoesNotPolluteCurrentCache() {
        val settings = ProviderSettingsStore().apply { saveServerUrl("https://api.example.com") }
        val tokenStore = ProviderTokenStore().apply { saveToken("bound-token") }
        val factory = RecordingApiFactory()
        val provider = ApiServiceProvider(factory, settings, tokenStore)

        val current = provider.current()
        val temporary = provider.temporary("https://pairing.example", tokenOverride = "pair-token")
        val currentAgain = provider.current()

        assertSame(current, currentAgain)
        assertFalse(current === temporary)
        assertEquals(
            listOf("https://api.example.com", "https://pairing.example"),
            factory.creations.map { it.baseUrl },
        )
        assertEquals("bound-token", factory.creations[0].tokenProvider())
        assertEquals("pair-token", factory.creations[1].tokenProvider())
    }

    @Test
    fun unauthenticatedServiceDoesNotReadStoredToken() {
        val settings = ProviderSettingsStore().apply { saveServerUrl("https://api.example.com") }
        val tokenStore = ProviderTokenStore().apply { saveToken("old-session-token") }
        val factory = RecordingApiFactory()
        val provider = ApiServiceProvider(factory, settings, tokenStore)

        provider.unauthenticated("https://pairing.example")

        assertEquals("https://pairing.example", factory.creations.single().baseUrl)
        assertNull(factory.creations.single().tokenProvider())
    }

    @Test
    fun clearDropsCurrentCache() {
        val settings = ProviderSettingsStore().apply { saveServerUrl("https://api.example.com") }
        val tokenStore = ProviderTokenStore().apply { saveToken("session-token") }
        val factory = RecordingApiFactory()
        val provider = ApiServiceProvider(factory, settings, tokenStore)

        val first = provider.current()
        provider.clear()
        val second = provider.current()

        assertFalse(first === second)
        assertEquals(2, factory.creations.size)
    }
}

private data class ApiCreation(
    val baseUrl: String,
    val tokenProvider: () -> String?,
    val service: ApiService,
)

private class RecordingApiFactory : ApiServiceFactory {
    val creations = mutableListOf<ApiCreation>()

    override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService {
        val service = Proxy.newProxyInstance(
            ApiService::class.java.classLoader,
            arrayOf(ApiService::class.java),
        ) { proxy, method, args ->
            when {
                method.declaringClass == Any::class.java && method.name == "toString" -> "ProviderApiProxy"
                method.declaringClass == Any::class.java && method.name == "hashCode" -> System.identityHashCode(proxy)
                method.declaringClass == Any::class.java && method.name == "equals" -> proxy === args?.firstOrNull()
                else -> error("Api method ${method.name} is not used in this test.")
            }
        } as ApiService
        creations += ApiCreation(baseUrl = baseUrl, tokenProvider = tokenProvider, service = service)
        return service
    }
}

private class ProviderSettingsStore : TicketboxSettingsStore {
    override val backgroundSettingsFlow: Flow<BackgroundSettings> = MutableStateFlow(BackgroundSettings())
    private var serverUrl: String? = null
    private var role: String? = "owner"
    private val ledgerIdFlow = MutableStateFlow<String?>(null)

    override fun serverUrl(): String? = serverUrl

    override fun appSkinKey(): String? = null

    override fun monthlyBudgetCents(): Long? = null

    override fun saveMonthlyBudgetCents(amountCents: Long?) = Unit

    override fun lastConfirmedSyncAt(): String? = null

    override fun accountName(): String? = null

    override fun ledgerName(): String? = null

    override fun activeLedgerId(): String? = ledgerIdFlow.value

    override fun activeLedgerName(): String? = null

    override fun availableLedgersJson(): String? = null

    override fun observeActiveLedgerId(): Flow<String?> = ledgerIdFlow

    override fun saveActiveLedger(ledgerId: String, ledgerName: String) {
        ledgerIdFlow.value = ledgerId
    }

    override fun saveAvailableLedgersJson(json: String?) = Unit

    override fun deviceName(): String? = null

    override fun role(): String? = role

    override fun boundAt(): String? = null

    override fun saveIdentity(
        accountName: String,
        ledgerId: String,
        ledgerName: String,
        deviceName: String,
        role: String,
        boundAt: String,
    ) {
        this.role = role
        ledgerIdFlow.value = ledgerId
    }

    override fun saveLastConfirmedSyncAt(value: String) = Unit

    override fun clearLastConfirmedSyncAt() = Unit

    override fun clearLastConfirmedSyncAtForLedger(ledgerId: String) = Unit

    override fun clearLedgerScopedRuntimeState() = Unit

    override fun lastUploadAt(): String? = null

    override fun saveLastUploadAt(value: String) = Unit

    override fun saveAppSkinKey(skinKey: String) = Unit

    override fun currencyCodeKey(): String? = null

    override fun saveCurrencyCodeKey(currencyKey: String) = Unit

    override fun observeCurrencyCodeKey(): Flow<String?> = MutableStateFlow(null)

    override fun saveServerUrl(serverUrl: String) {
        this.serverUrl = serverUrl.trim().trimEnd('/')
    }

    override fun isBound(): Boolean = !serverUrl.isNullOrBlank()

    override fun markUnlocked() = Unit

    override fun markBackgrounded() = Unit

    override fun requiresUnlock(): Boolean = false

    override fun clear() {
        serverUrl = null
        role = null
        ledgerIdFlow.value = null
    }
}

private class ProviderTokenStore : SessionTokenStore {
    private var token: String? = null

    override fun saveToken(token: String) {
        this.token = token
    }

    override fun getToken(): String? = token

    override fun clear() {
        token = null
    }
}
