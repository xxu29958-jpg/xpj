package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.SessionAwareApiServiceFactory
import com.ticketbox.security.LocalSessionIdentity
import com.ticketbox.security.LocalSessionRecord
import com.ticketbox.security.SessionCredentialAdapter
import com.ticketbox.security.SessionCredentialRotator
import com.ticketbox.security.StoredSessionToken
import java.lang.reflect.Proxy
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull

class ApiServiceProviderTest {
    @Test
    fun boundServiceKeepsIntentLedgerAndOnlyReadsItsOriginalSession() {
        val sessionStore = providerSessionStore(token = "token-1")
        val factory = RecordingApiFactory()
        val provider = provider(factory, sessionStore)

        provider.bound(
            serverUrl = "https://api.example.com",
            sessionGeneration = "session-1",
            ledgerId = "owner",
        )

        assertEquals(1, factory.creations.size)
        assertEquals("token-1", factory.creations.single().tokenProvider())
        assertEquals("owner", factory.creations.single().ledgerIdProvider())

        val currentSession = requireNotNull(sessionStore.currentSession())
        sessionStore.replaceForFixture(
            currentSession.copy(
                bindingRevision = "binding-2",
                credential = StoredSessionToken("token-2"),
                identity = currentSession.identity.copy(
                    ledgerId = "family",
                    ledgerName = "家庭账本",
                ),
            ),
        )

        assertEquals("token-2", factory.creations.single().tokenProvider())
        assertEquals("owner", factory.creations.single().ledgerIdProvider())

        sessionStore.replaceForFixture(
            requireNotNull(sessionStore.currentSession()).copy(
                sessionGeneration = "session-2",
                bindingRevision = "binding-3",
                credential = StoredSessionToken("other-account-token"),
            ),
        )

        assertNull(factory.creations.single().tokenProvider())
        assertNull(factory.creations.single().ledgerIdProvider())
    }

    @Test
    fun requestGuardRejectsAnotherOwnerAndAChangedBinding() {
        val sessionStore = providerSessionStore()
        val factory = RecordingApiFactory()
        val provider = provider(factory, sessionStore)
        val bound = LedgerRequestGuard(provider).bind(expectedLedgerId = "owner")
        val otherOwner = requireNotNull(
            OutboxOwnerIdentity.fromOrNull(
                serverId = TEST_SERVER_ID,
                dataGeneration = TEST_DATA_GENERATION,
                accountPublicId = TEST_ACCOUNT_PUBLIC_ID,
                devicePublicId = "10000000-0000-0000-0000-000000000099",
            ),
        )

        assertFailsWith<RepositoryException> {
            bound.serviceFor(OutboxBinding("https://api.example.com", "owner", otherOwner))
        }

        sessionStore.replaceForFixture(
            requireNotNull(sessionStore.currentSession()).copy(bindingRevision = "binding-2"),
        )
        assertFailsWith<RepositoryException> { bound.requireStillActive() }
    }

    @Test
    fun unauthenticatedServiceDoesNotReadStoredToken() {
        val sessionStore = providerSessionStore(token = "old-session-token")
        val factory = RecordingApiFactory()
        val provider = provider(factory, sessionStore)

        provider.unauthenticated("https://pairing.example")

        assertEquals("https://pairing.example", factory.creations.single().baseUrl)
        assertNull(factory.creations.single().tokenProvider())
    }

}

private fun provider(
    factory: ApiServiceFactory,
    sessionStore: InMemoryLocalSessionStore,
): ApiServiceProvider = ApiServiceProvider(
    apiClient = factory,
    sessionStore = sessionStore,
    credentials = SessionCredentialAdapter(sessionStore),
)

private fun providerSessionStore(
    serverUrl: String = "https://api.example.com",
    token: String = "session-token",
): InMemoryLocalSessionStore = InMemoryLocalSessionStore(
    LocalSessionRecord(
        sessionGeneration = "session-1",
        bindingRevision = "binding-1",
        serverId = TEST_SERVER_ID,
        dataGeneration = TEST_DATA_GENERATION,
        serverUrl = serverUrl,
        credential = StoredSessionToken(token),
        identity = LocalSessionIdentity(
            accountPublicId = TEST_ACCOUNT_PUBLIC_ID,
            devicePublicId = TEST_DEVICE_PUBLIC_ID,
            accountName = "我",
            ledgerId = "owner",
            ledgerName = "我的小票夹",
            deviceName = "Pixel",
            role = "owner",
            boundAt = "2026-05-01T00:00:00Z",
        ),
    ),
)

private data class ApiCreation(
    val baseUrl: String,
    val tokenProvider: () -> String?,
    val ledgerIdProvider: () -> String?,
    val service: ApiService,
)

private class RecordingApiFactory : SessionAwareApiServiceFactory {
    val creations = mutableListOf<ApiCreation>()

    override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService =
        record(baseUrl, tokenProvider) { null }

    override fun create(baseUrl: String, credentials: SessionCredentialRotator): ApiService =
        record(baseUrl, credentials::getToken, credentials::currentLedgerId)

    private fun record(
        baseUrl: String,
        tokenProvider: () -> String?,
        ledgerIdProvider: () -> String?,
    ): ApiService {
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
        creations += ApiCreation(
            baseUrl = baseUrl,
            tokenProvider = tokenProvider,
            ledgerIdProvider = ledgerIdProvider,
            service = service,
        )
        return service
    }
}
