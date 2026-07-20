package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.SessionAwareApiServiceFactory
import com.ticketbox.security.LocalSessionRecord
import com.ticketbox.security.LocalSessionStore
import com.ticketbox.security.LocalSessionVersion
import com.ticketbox.security.PendingSessionRefresh
import com.ticketbox.security.RequestAuthSnapshot
import com.ticketbox.security.SessionCredentialRotator
import com.ticketbox.security.StoredSessionToken
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map

/** Builds API services from explicit local-session snapshots. */
class ApiServiceProvider(
    private val apiClient: ApiServiceFactory,
    private val sessionStore: LocalSessionStore,
    private val credentials: SessionCredentialRotator,
) {
    internal fun bound(
        serverUrl: String,
        expectedVersion: LocalSessionVersion,
        ledgerId: String,
    ): ApiService {
        val cleanServerUrl = requireServerUrl(serverUrl)
        val scopedCredentials = ScopedSessionCredentials(
            delegate = credentials,
            expectedVersion = expectedVersion,
            ledgerId = ledgerId,
        )
        return if (apiClient is SessionAwareApiServiceFactory) {
            apiClient.create(cleanServerUrl, scopedCredentials)
        } else {
            apiClient.create(
                cleanServerUrl,
                scopedCredentials::getToken,
                scopedCredentials::currentLedgerId,
            )
        }
    }

    fun unauthenticated(serverUrl: String): ApiService =
        apiClient.create(requireServerUrl(serverUrl)) { null }

    internal fun currentSession(): LocalSessionRecord? = sessionStore.currentSession()

    internal fun currentLedgerRole(): String? = currentSession()?.identity?.role

    internal fun currentLedgerId(): String? = currentSession()?.identity?.ledgerId

    internal fun observeActiveLedgerId(): Flow<String?> =
        sessionStore.observeSession()
            .map { session -> session?.identity?.ledgerId }
            .distinctUntilChanged()

    private fun requireServerUrl(value: String?): String {
        val serverUrl = value?.trim()?.trimEnd('/')
        require(!serverUrl.isNullOrBlank()) { "账本地址未绑定" }
        return serverUrl
    }
}

private class ScopedSessionCredentials(
    private val delegate: SessionCredentialRotator,
    private val expectedVersion: LocalSessionVersion,
    private val ledgerId: String,
) : SessionCredentialRotator {
    override fun getToken(): String? =
        requestAuthSnapshot()?.credential?.token

    override fun currentLedgerId(): String? =
        requestAuthSnapshot()?.ledgerId

    override fun getSessionToken(): StoredSessionToken? =
        requestAuthSnapshot()?.credential

    override fun sessionGeneration(): String? =
        expectedVersion.sessionGeneration.takeIf { isCurrentGeneration() }

    override fun requestAuthSnapshot(): RequestAuthSnapshot? =
        delegate.requestAuthSnapshot()?.takeIf { snapshot ->
            snapshot.version == expectedVersion && snapshot.ledgerId == ledgerId
        }

    override suspend fun beginOrReuseSessionRefresh(
        expectedSessionGeneration: String,
        expectedToken: String,
    ): PendingSessionRefresh? {
        if (expectedSessionGeneration != expectedVersion.sessionGeneration || !isCurrentGeneration()) {
            return null
        }
        return delegate.beginOrReuseSessionRefresh(
            expectedSessionGeneration = expectedSessionGeneration,
            expectedToken = expectedToken,
        )
    }

    override suspend fun resumeSessionRefresh(
        expectedSessionGeneration: String,
        expectedToken: String,
    ): PendingSessionRefresh? {
        if (expectedSessionGeneration != expectedVersion.sessionGeneration || !isCurrentGeneration()) {
            return null
        }
        return delegate.resumeSessionRefresh(
            expectedSessionGeneration = expectedSessionGeneration,
            expectedToken = expectedToken,
        )
    }

    override suspend fun completeSessionRefreshIfCurrent(
        expectedSessionGeneration: String,
        expectedToken: String,
        refreshAttemptId: String,
        replacement: StoredSessionToken,
    ): Boolean {
        if (expectedSessionGeneration != expectedVersion.sessionGeneration || !isCurrentGeneration()) {
            return false
        }
        return delegate.completeSessionRefreshIfCurrent(
            expectedSessionGeneration = expectedSessionGeneration,
            expectedToken = expectedToken,
            refreshAttemptId = refreshAttemptId,
            replacement = replacement,
        )
    }

    private fun isCurrentGeneration(): Boolean =
        delegate.sessionGeneration() == expectedVersion.sessionGeneration
}
