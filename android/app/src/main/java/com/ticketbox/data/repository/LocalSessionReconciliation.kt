package com.ticketbox.data.repository

import com.ticketbox.data.local.LegacySessionProjectionStore
import com.ticketbox.data.local.PersistedLedgerIdentity
import com.ticketbox.security.LocalSessionIdentity
import com.ticketbox.security.LocalSessionRecord
import com.ticketbox.security.LocalSessionStore
import com.ticketbox.security.StoredSessionToken
import java.util.UUID

/** Import one complete legacy session, then retire every legacy session field. */
internal suspend fun reconcileLocalSession(
    legacyProjectionStore: LegacySessionProjectionStore,
    sessionStore: LocalSessionStore,
    legacyCredential: StoredSessionToken?,
) {
    if (sessionStore.hasPersistedSessionState()) {
        val session = sessionStore.currentSession()
        val recoverableEnrollment = sessionStore.pendingDeviceEnrollment()
            ?.takeIf { sessionStore.sessionRefresh.pending() == null }
        if (session == null && recoverableEnrollment != null) {
            legacyProjectionStore.clearLegacySessionProjection()
            return
        }
        if (session == null || canonicalServerOriginOrNull(session.serverUrl) != session.serverUrl) {
            clearInvalidSession(sessionStore, legacyProjectionStore)
            return
        }
        legacyProjectionStore.clearLegacySessionProjection()
        return
    }

    val projection = legacyProjectionStore.readLegacySessionProjection()
    val canonicalServerUrl = projection?.serverUrl?.let(::canonicalServerOriginOrNull)
    if (legacyCredential == null || projection == null || canonicalServerUrl == null) {
        clearInvalidSession(sessionStore, legacyProjectionStore)
        return
    }

    val migrated = LocalSessionRecord(
        sessionGeneration = UUID.randomUUID().toString(),
        bindingRevision = UUID.randomUUID().toString(),
        serverUrl = canonicalServerUrl,
        credential = legacyCredential,
        identity = projection.identity.toLocalSessionIdentity(),
    )
    sessionStore.establishSession(migrated)
    legacyProjectionStore.clearLegacySessionProjection()
}

private suspend fun clearInvalidSession(
    sessionStore: LocalSessionStore,
    legacyProjectionStore: LegacySessionProjectionStore,
) {
    sessionStore.clearSession()
    legacyProjectionStore.clearLegacySessionProjection()
}

internal fun PersistedLedgerIdentity.toLocalSessionIdentity(): LocalSessionIdentity =
    LocalSessionIdentity(
        accountName = accountName,
        ledgerId = ledgerId,
        ledgerName = ledgerName,
        deviceName = deviceName,
        role = role,
        boundAt = boundAt,
    )
