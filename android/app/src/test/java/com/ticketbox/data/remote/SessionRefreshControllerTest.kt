package com.ticketbox.data.remote

import com.ticketbox.data.remote.dto.RefreshSessionRequestDto
import com.ticketbox.data.remote.dto.RefreshSessionResponseDto
import com.ticketbox.data.repository.FakeApiService
import com.ticketbox.data.repository.InMemoryLocalSessionStore
import com.ticketbox.security.LocalSessionIdentity
import com.ticketbox.security.LocalSessionRecord
import com.ticketbox.security.SessionCredentialAdapter
import com.ticketbox.security.StoredSessionToken
import java.io.IOException
import java.time.Instant
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class SessionRefreshControllerTest {
    private val scheduler = SessionRefreshScheduler()

    @Test
    fun responseLossReusesPersistedAttemptAfterControllerReconstruction() {
        val session = session()
        val store = InMemoryLocalSessionStore(session)
        val credentials = SessionCredentialAdapter(store)
        val api = ResponseLossRefreshApi()

        controller(credentials, api).refreshAsync(Instant.parse("2026-07-15T00:00:00Z"))
        assertTrue(api.firstRequestFinished.await(2, TimeUnit.SECONDS))
        val pendingAfterLoss = assertNotNull(store.sessionRefresh.pending())

        controller(credentials, api).refreshAsync(Instant.parse("2026-07-15T00:00:01Z"))
        assertTrue(api.secondRequestFinished.await(2, TimeUnit.SECONDS))
        awaitCredential(store, "token-after-refresh")

        assertEquals(2, api.requests.size)
        assertEquals(api.requests[0], api.requests[1])
        assertEquals(pendingAfterLoss.attemptId, api.requests[1].refreshAttemptId)
        assertEquals(session.sessionGeneration, store.currentSession()?.sessionGeneration)
        assertEquals(null, store.sessionRefresh.pending())
    }

    @Test
    fun controllersSharingSchedulerCoalesceConcurrentRefresh() {
        val store = InMemoryLocalSessionStore(session())
        val credentials = SessionCredentialAdapter(store)
        val api = BlockingRefreshApi()

        controller(credentials, api).refreshAsync(Instant.parse("2026-07-15T00:00:00Z"))
        assertTrue(api.requestStarted.await(2, TimeUnit.SECONDS))
        controller(credentials, api).refreshAsync(Instant.parse("2026-07-15T00:00:01Z"))
        api.allowResponse.countDown()
        assertTrue(api.requestFinished.await(2, TimeUnit.SECONDS))
        awaitCredential(store, "token-after-refresh")

        assertEquals(1, api.requestCount)
    }

    private fun controller(
        credentials: SessionCredentialAdapter,
        api: ApiService,
    ) = SessionRefreshController(
        baseUrl = "https://api.example.com",
        credentials = credentials,
        scheduler = scheduler,
        serviceFactory = { _, _ -> api },
    )

    private fun awaitCredential(store: InMemoryLocalSessionStore, expected: String) {
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(2)
        while (store.currentSession()?.credential?.token != expected && System.nanoTime() < deadline) {
            Thread.sleep(10)
        }
        assertEquals(expected, store.currentSession()?.credential?.token)
    }

    private fun session() = LocalSessionRecord(
        sessionGeneration = "session-one",
        bindingRevision = "binding-one",
        serverId = "70000000-0000-0000-0000-000000000001",
        dataGeneration = "70000000-0000-0000-0000-000000000002",
        serverUrl = "https://api.example.com",
        credential = StoredSessionToken(
            token = "token-before-refresh",
            expiresAt = "2026-08-15T00:00:00Z",
            softRefreshAfter = "2026-07-14T00:00:00Z",
        ),
        identity = LocalSessionIdentity(
            accountPublicId = "70000000-0000-0000-0000-000000000003",
            devicePublicId = "70000000-0000-0000-0000-000000000004",
            accountName = "我",
            ledgerId = "ledger-a",
            ledgerName = "家庭账本",
            deviceName = "Pixel",
            role = "owner",
            boundAt = "2026-07-14T00:00:00Z",
        ),
    )
}

private class BlockingRefreshApi(
    private val delegate: ApiService = FakeApiService(mutableListOf(), 0),
) : ApiService by delegate {
    val requestStarted = CountDownLatch(1)
    val allowResponse = CountDownLatch(1)
    val requestFinished = CountDownLatch(1)
    var requestCount: Int = 0
        private set

    override suspend fun refreshSession(request: RefreshSessionRequestDto): RefreshSessionResponseDto {
        requestCount += 1
        requestStarted.countDown()
        check(allowResponse.await(2, TimeUnit.SECONDS))
        requestFinished.countDown()
        return RefreshSessionResponseDto(
            sessionToken = "token-after-refresh",
            refreshAttemptId = request.refreshAttemptId,
            expiresAt = "2026-08-15T00:00:00Z",
            softRefreshAfter = "2026-08-08T00:00:00Z",
            rotated = true,
        )
    }
}

private class ResponseLossRefreshApi(
    private val delegate: ApiService = FakeApiService(mutableListOf(), 0),
) : ApiService by delegate {
    val requests = mutableListOf<RefreshSessionRequestDto>()
    val firstRequestFinished = CountDownLatch(1)
    val secondRequestFinished = CountDownLatch(1)

    override suspend fun refreshSession(
        request: RefreshSessionRequestDto,
    ): RefreshSessionResponseDto {
        val requestCount = synchronized(requests) {
            requests += request
            requests.size
        }
        if (requestCount == 1) {
            firstRequestFinished.countDown()
            throw IOException("response lost after server commit")
        }
        secondRequestFinished.countDown()
        return RefreshSessionResponseDto(
            sessionToken = "token-after-refresh",
            refreshAttemptId = request.refreshAttemptId,
            expiresAt = "2026-08-15T00:00:00Z",
            softRefreshAfter = "2026-08-08T00:00:00Z",
            rotated = true,
        )
    }
}
