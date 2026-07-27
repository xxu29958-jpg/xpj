package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiClient
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.SessionAwareApiServiceFactory
import com.ticketbox.domain.model.BudgetMonthlyUpdate
import com.ticketbox.security.LocalSessionIdentity
import com.ticketbox.security.LocalSessionRecord
import com.ticketbox.security.SessionCredentialAdapter
import com.ticketbox.security.SessionCredentialRotator
import com.ticketbox.security.StoredSessionToken
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.yield
import java.io.IOException
import java.lang.reflect.Proxy
import java.net.ServerSocket
import java.net.SocketTimeoutException
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import kotlin.concurrent.thread
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

class ApiServiceProviderTest {
    @Test
    fun boundServiceKeepsIntentLedgerAndOnlyReadsItsOriginalSession() {
        val sessionStore = providerSessionStore(token = "token-1")
        val factory = RecordingApiFactory()
        val provider = provider(factory, sessionStore)
        val initial = requireNotNull(sessionStore.currentSession())

        provider.bound(
            serverUrl = "https://api.example.com",
            expectedVersion = initial.version,
            ledgerId = "owner",
        )

        assertEquals(1, factory.creations.size)
        assertEquals("token-1", factory.creations.single().tokenProvider())
        assertEquals("owner", factory.creations.single().ledgerIdProvider())

        sessionStore.replaceForFixture(
            initial.copy(
                credential = StoredSessionToken("token-2"),
            ),
        )

        assertEquals("token-2", factory.creations.single().tokenProvider())
        assertEquals("owner", factory.creations.single().ledgerIdProvider())

        sessionStore.replaceForFixture(
            requireNotNull(sessionStore.currentSession()).copy(
                bindingRevision = "binding-2",
                identity = initial.identity.copy(
                    ledgerId = "family",
                    ledgerName = "家庭账本",
                ),
            ),
        )

        assertNull(factory.creations.single().tokenProvider())
        assertNull(factory.creations.single().ledgerIdProvider())

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
    fun requestInvalidatedBeforeAuthSnapshotDoesNotReachNetwork() {
        ServerSocket(0).use { server ->
            server.soTimeout = 300
            val sessionStore = providerSessionStore(
                serverUrl = "http://127.0.0.1:${server.localPort}",
            )
            val initial = requireNotNull(sessionStore.currentSession())
            val credentials = BlockingSessionCredentials(SessionCredentialAdapter(sessionStore))
            val provider = ApiServiceProvider(ApiClient(), sessionStore, credentials)
            val service = provider.bound(
                serverUrl = initial.serverUrl,
                expectedVersion = initial.version,
                ledgerId = initial.identity.ledgerId,
            )
            val failure = AtomicReference<Throwable>()
            val request = thread(name = "ticketbox-auth-snapshot-race") {
                failure.set(runCatching { runBlocking { service.checkAuth() } }.exceptionOrNull())
            }

            assertTrue(credentials.readStarted.await(2, TimeUnit.SECONDS))
            sessionStore.replaceForFixture(
                initial.copy(
                    bindingRevision = "binding-2",
                    identity = initial.identity.copy(
                        ledgerId = "family",
                        ledgerName = "家庭账本",
                    ),
                ),
            )
            credentials.continueRead.countDown()
            request.join(5_000)

            assertTrue(!request.isAlive)
            assertTrue(failure.get() is IOException)
            assertFailsWith<SocketTimeoutException> { server.accept() }
        }
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
    fun activeLedgerAccessSeparatesRoleFromIdentityAndIgnoresTokenRotation() = runBlocking {
        val sessionStore = providerSessionStore(token = "token-1")
        val provider = provider(RecordingApiFactory(), sessionStore)
        val initial = requireNotNull(sessionStore.currentSession())
        val emissions = mutableListOf<LedgerAccessContext?>()
        val collection = launch(start = CoroutineStart.UNDISPATCHED) {
            provider.observeActiveLedgerAccess().collect(emissions::add)
        }
        assertEquals(1, emissions.size)

        sessionStore.replaceForFixture(
            initial.copy(identity = initial.identity.copy(role = "viewer")),
        )
        yield()
        assertEquals(2, emissions.size)
        sessionStore.replaceForFixture(
            requireNotNull(sessionStore.currentSession()).copy(
                credential = StoredSessionToken("token-2"),
            ),
        )
        yield()
        assertEquals(2, emissions.size)
        sessionStore.replaceForFixture(
            requireNotNull(sessionStore.currentSession()).copy(bindingRevision = "binding-2"),
        )
        yield()
        assertEquals(3, emissions.size)
        collection.cancelAndJoin()

        val (owner, viewer, rebound) = emissions.map(::requireNotNull)
        assertTrue(owner.canModify)
        assertFalse(viewer.canModify)
        assertEquals(owner.binding, viewer.binding)
        assertEquals("binding-2", rebound.binding.bindingRevision)
    }

    @Test
    fun planRepositoriesRejectAStaleBindingBeforeCreatingAnApiService() = runBlocking {
        val sessionStore = providerSessionStore()
        val factory = RecordingApiFactory()
        val provider = provider(factory, sessionStore)
        val binding = requireNotNull(LedgerRequestGuard(provider).captureLogicalBinding())
        sessionStore.replaceForFixture(
            requireNotNull(sessionStore.currentSession()).copy(bindingRevision = "binding-2"),
        )

        val results = listOf(
            BudgetRepository(provider).monthlyBudget(binding, "2026-05"),
            RecurringRepository(provider).items(binding, includeArchived = true),
            IncomePlanRepository(provider).listActive(binding),
            BudgetRepository(provider).saveMonthlyBudget(
                binding,
                "2026-05",
                BudgetMonthlyUpdate(totalAmountCents = 300_000),
            ),
            RecurringRepository(provider).pause(binding, "recurring-1", expectedRowVersion = 1L),
            IncomePlanRepository(provider).archive(binding, "income-1", expectedRowVersion = 1L),
        )

        assertTrue(results.all(Result<*>::isFailure))
        assertTrue(factory.creations.isEmpty())
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

private class BlockingSessionCredentials(
    private val delegate: SessionCredentialRotator,
) : SessionCredentialRotator by delegate {
    val readStarted = CountDownLatch(1)
    val continueRead = CountDownLatch(1)

    override fun requestAuthSnapshot() = run {
        readStarted.countDown()
        check(continueRead.await(2, TimeUnit.SECONDS))
        delegate.requestAuthSnapshot()
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
