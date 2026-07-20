package com.ticketbox.data.repository

import com.ticketbox.security.LocalSessionRecord
import java.util.UUID

/** Stable server-issued owner of a durable offline mutation. */
@ConsistentCopyVisibility
data class OutboxOwnerIdentity private constructor(
    val serverId: String,
    val dataGeneration: String,
    val accountPublicId: String,
    val devicePublicId: String,
) {
    val storageKey: String = listOf(
        STORAGE_VERSION,
        serverId,
        dataGeneration,
        accountPublicId,
        devicePublicId,
    ).joinToString(STORAGE_SEPARATOR)

    companion object {
        private const val STORAGE_VERSION = "v1"
        private const val STORAGE_SEPARATOR = ":"

        fun fromOrNull(
            serverId: String?,
            dataGeneration: String?,
            accountPublicId: String?,
            devicePublicId: String?,
        ): OutboxOwnerIdentity? {
            val canonicalIds = listOf(
                serverId,
                dataGeneration,
                accountPublicId,
                devicePublicId,
            ).map { it.canonicalUuidOrNull() ?: return null }
            return OutboxOwnerIdentity(
                serverId = canonicalIds[0],
                dataGeneration = canonicalIds[1],
                accountPublicId = canonicalIds[2],
                devicePublicId = canonicalIds[3],
            )
        }

        fun parseOrNull(value: String?): OutboxOwnerIdentity? {
            val parts = value?.split(STORAGE_SEPARATOR) ?: return null
            if (parts.size != 5 || parts.first() != STORAGE_VERSION) return null
            return fromOrNull(
                serverId = parts[1],
                dataGeneration = parts[2],
                accountPublicId = parts[3],
                devicePublicId = parts[4],
            )?.takeIf { it.storageKey == value }
        }

        private fun String?.canonicalUuidOrNull(): String? {
            val candidate = this?.trim()?.takeIf(String::isNotEmpty) ?: return null
            val canonical = try {
                UUID.fromString(candidate).toString()
            } catch (_: IllegalArgumentException) {
                return null
            }
            return canonical.takeIf { it == candidate }
        }
    }
}

internal fun LocalSessionRecord?.toOutboxBinding(): OutboxBinding {
    val session = this ?: return OutboxBinding.DEFAULT
    return OutboxBinding(
        serverUrl = session.serverUrl,
        ledgerId = session.identity.ledgerId,
        owner = OutboxOwnerIdentity.fromOrNull(
            serverId = session.serverId,
            dataGeneration = session.dataGeneration,
            accountPublicId = session.identity.accountPublicId,
            devicePublicId = session.identity.devicePublicId,
        ),
    )
}
