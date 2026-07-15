package com.ticketbox.data.remote

import android.util.Log
import com.ticketbox.data.remote.dto.RefreshSessionRequestDto
import com.ticketbox.data.remote.dto.RefreshSessionResponseDto
import com.ticketbox.security.SessionCredentialRotator
import com.ticketbox.security.StoredSessionToken
import kotlinx.coroutines.runBlocking
import java.time.Instant
import java.time.OffsetDateTime
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

internal class SessionRefreshController(
    private val baseUrl: String,
    private val credentials: SessionCredentialRotator,
    private val serviceFactory: (String, () -> String?) -> ApiService,
    private val scheduler: SessionRefreshScheduler,
) {
    fun refreshAsync(now: Instant = Instant.now()) {
        val snapshot = credentials.getSessionToken() ?: return
        val sessionGeneration = credentials.sessionGeneration() ?: return
        if (!shouldRefresh(snapshot, now)) return
        scheduler.execute {
            try {
                runBlocking {
                    refreshIfCurrent(sessionGeneration, snapshot)
                }
            } catch (error: Exception) {
                Log.w(LOG_TAG, "Silent session refresh failed: ${error::class.java.simpleName}")
            }
        }
    }

    private suspend fun refreshIfCurrent(
        sessionGeneration: String,
        snapshot: StoredSessionToken,
    ) {
        if (credentials.sessionGeneration() != sessionGeneration ||
            credentials.getToken() != snapshot.token
        ) {
            return
        }
        val attempt = credentials.beginOrReuseSessionRefresh(
            expectedSessionGeneration = sessionGeneration,
            expectedToken = snapshot.token,
        ) ?: return
        val api = serviceFactory(baseUrl) { snapshot.token }
        val response = api.refreshSession(
            RefreshSessionRequestDto(
                refreshAttemptId = attempt.attemptId,
                refreshAttemptSecret = attempt.attemptSecret,
            ),
        )
        if (response.rotated) {
            check(response.refreshAttemptId == attempt.attemptId) {
                "Session refresh response did not match the pending attempt."
            }
        } else {
            check(response.sessionToken == snapshot.token) {
                "A non-rotating refresh changed the session credential."
            }
        }
        credentials.completeSessionRefreshIfCurrent(
            expectedSessionGeneration = sessionGeneration,
            expectedToken = snapshot.token,
            refreshAttemptId = attempt.attemptId,
            replacement = StoredSessionToken(
                token = response.sessionToken,
                expiresAt = response.expiresAt,
                softRefreshAfter = response.softRefreshAfter,
            ),
        )
    }

    private companion object {
        const val LOG_TAG = "TicketboxNetwork"
    }
}

/** One app-level refresh queue shared by every short-lived bound API service. */
internal class SessionRefreshScheduler {
    private val refreshing = AtomicBoolean(false)
    private val executor = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "ticketbox-session-refresh").apply { isDaemon = true }
    }

    fun execute(block: () -> Unit) {
        if (!refreshing.compareAndSet(false, true)) return
        executor.execute {
            try {
                block()
            } finally {
                refreshing.set(false)
            }
        }
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
