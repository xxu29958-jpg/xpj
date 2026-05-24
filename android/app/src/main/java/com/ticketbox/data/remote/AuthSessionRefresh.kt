package com.ticketbox.data.remote

import android.util.Log
import com.ticketbox.data.remote.dto.RefreshSessionResponseDto
import com.ticketbox.security.SessionTokenStore
import com.ticketbox.security.StoredSessionToken
import kotlinx.coroutines.runBlocking
import java.time.Instant
import java.time.OffsetDateTime
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

internal class SessionRefreshController(
    private val baseUrl: String,
    private val tokenStore: SessionTokenStore,
    private val serviceFactory: (String, () -> String?) -> ApiService,
) {
    private val refreshing = AtomicBoolean(false)
    private val executor = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "ticketbox-session-refresh").apply { isDaemon = true }
    }

    fun refreshAsync(now: Instant = Instant.now()) {
        val snapshot = tokenStore.getSessionToken() ?: return
        if (!shouldRefresh(snapshot, now)) return
        if (!refreshing.compareAndSet(false, true)) return
        executor.execute {
            try {
                runBlocking {
                    refreshIfCurrent(snapshot)
                }
            } catch (error: Exception) {
                Log.w(LOG_TAG, "Silent session refresh failed: ${error::class.java.simpleName}")
            } finally {
                refreshing.set(false)
            }
        }
    }

    private suspend fun refreshIfCurrent(snapshot: StoredSessionToken) {
        if (tokenStore.getToken() != snapshot.token) return
        val api = serviceFactory(baseUrl) { snapshot.token }
        val response = api.refreshSession()
        if (tokenStore.getToken() != snapshot.token) return
        persistRefresh(response)
    }

    private fun persistRefresh(response: RefreshSessionResponseDto) {
        tokenStore.saveToken(
            token = response.sessionToken,
            expiresAt = response.expiresAt,
            softRefreshAfter = response.softRefreshAfter,
        )
    }

    private companion object {
        const val LOG_TAG = "TicketboxNetwork"
    }
}

internal fun isExpired(session: StoredSessionToken, now: Instant = Instant.now()): Boolean {
    val expiresAt = parseInstantOrNull(session.expiresAt) ?: return false
    return !now.isBefore(expiresAt)
}

internal fun shouldRefresh(session: StoredSessionToken, now: Instant = Instant.now()): Boolean {
    if (isExpired(session, now)) return false
    val softRefreshAfter = parseInstantOrNull(session.softRefreshAfter) ?: return false
    return !now.isBefore(softRefreshAfter)
}

private fun parseInstantOrNull(value: String?): Instant? {
    val raw = value?.trim()?.takeIf { it.isNotBlank() } ?: return null
    return runCatching { Instant.parse(raw) }
        .recoverCatching { OffsetDateTime.parse(raw).toInstant() }
        .getOrNull()
}
