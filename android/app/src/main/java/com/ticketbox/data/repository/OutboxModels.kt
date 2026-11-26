package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationEntity
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

internal val OUTBOX_ISO_FORMATTER: DateTimeFormatter = DateTimeFormatter
    .ofPattern("uuuu-MM-dd'T'HH:mm:ss.SSS'Z'")
    .withZone(ZoneOffset.UTC)

internal fun Clock.outboxNowIso(): String = OUTBOX_ISO_FORMATTER.format(Instant.now(this))

internal fun Clock.outboxOverAgeCutoffIso(): String =
    OUTBOX_ISO_FORMATTER.format(Instant.now(this).minusMillis(OUTBOX_PENDING_AGE_CAP_MILLIS))

internal data class PendingMutationIntent(
    val type: PendingMutationType,
    val targetId: String,
    val payloadJson: String,
    val expectedRowVersion: Long,
    val idempotencyKey: String? = null,
) {
    fun toEntity(binding: OutboxBinding, createdAt: String): PendingMutationEntity = PendingMutationEntity(
        serverUrl = binding.serverUrl,
        ledgerId = binding.ledgerId,
        ownerKey = requireNotNull(binding.owner).storageKey,
        type = type.wireValue,
        targetId = targetId,
        payload = payloadJson,
        expectedRowVersion = expectedRowVersion,
        idempotencyKey = idempotencyKey,
        status = PendingMutationStatus.Pending.wireValue,
        createdAt = createdAt,
    )
}

data class OutboxRow(
    val id: Long,
    val serverUrl: String,
    val ledgerId: String,
    val ownerKey: String? = null,
    val type: PendingMutationType,
    val targetId: String,
    val payloadJson: String,
    val expectedRowVersion: Long,
    val status: PendingMutationStatus,
    val retryCount: Int,
    val lastError: String?,
    val createdAt: String,
    val attemptedAt: String?,
    val completedAt: String?,
    val idempotencyKey: String? = null,
    val receiptJson: String? = null,
    val blocksFollowing: Boolean = true,
)

internal fun OutboxRow.bindingOrNull(): OutboxBinding? {
    val owner = OutboxOwnerIdentity.parseOrNull(ownerKey) ?: return null
    val canonicalOrigin = canonicalServerOriginOrNull(serverUrl) ?: return null
    val cleanLedgerId = ledgerId.trim().takeIf(String::isNotEmpty) ?: return null
    return OutboxBinding(
        serverUrl = canonicalOrigin,
        ledgerId = cleanLedgerId,
        owner = owner,
    )
}

data class OutboxBinding(
    val serverUrl: String,
    val ledgerId: String,
    val owner: OutboxOwnerIdentity?,
) {
    internal val ownerStorageKey: String
        get() = owner?.storageKey.orEmpty()

    internal fun trimmed(): OutboxBinding =
        OutboxBinding(
            serverUrl = serverUrl.trim().trimEnd('/'),
            ledgerId = ledgerId.trim(),
            owner = owner,
        )

    fun normalized(): OutboxBinding {
        val trimmed = trimmed()
        return trimmed.copy(
            serverUrl = canonicalServerOriginOrNull(trimmed.serverUrl) ?: trimmed.serverUrl,
        )
    }

    internal fun requireReadyForEnqueue() {
        if (serverUrl.isBlank() || ledgerId.isBlank() || owner == null) {
            throw RepositoryException("设备身份尚未完成校验，已停止保存离线操作。")
        }
    }

    companion object {
        val DEFAULT = OutboxBinding(serverUrl = "", ledgerId = "", owner = null)
    }
}

data class OutboxServerAliasMigration(
    val oldServerUrl: String,
    val newServerUrl: String,
    val ledgerId: String,
) {
    init {
        val oldCanonical = canonicalServerOriginOrNull(oldServerUrl)
        require(
            ledgerId.isNotBlank() &&
                oldCanonical != null &&
                oldCanonical == newServerUrl &&
                oldCanonical == canonicalServerOriginOrNull(newServerUrl),
        ) {
            "Outbox rows may only migrate between aliases of one canonical origin."
        }
    }
}

data class OutboxStatus(
    val queueDepth: Int,
    val conflicts: List<OutboxRow>,
    val failed: List<OutboxRow>,
    val quarantinedCount: Int = 0,
    val writeBlock: OutboxWriteBlock? = null,
    val binding: OutboxBinding? = null,
    val refreshRequired: List<OutboxRow> = emptyList(),
    val queuedRows: List<OutboxRow> = emptyList(),
) {
    val needsUserAction: Boolean
        get() = conflicts.isNotEmpty() || failed.isNotEmpty() || quarantinedCount > 0 || refreshRequired.isNotEmpty()
}

enum class OutboxWriteBlock {
    CLIENT_UPGRADE_REQUIRED,
    CURRENCY_ADOPTION_REQUIRED,
}

internal fun PendingMutationEntity.toDomain(): OutboxRow = OutboxRow(
    id = id,
    serverUrl = serverUrl,
    ledgerId = ledgerId,
    ownerKey = ownerKey,
    type = PendingMutationType.fromWire(type),
    targetId = targetId,
    payloadJson = payload,
    expectedRowVersion = expectedRowVersion,
    status = PendingMutationStatus.fromWire(status),
    retryCount = retryCount,
    lastError = lastError,
    createdAt = createdAt,
    attemptedAt = attemptedAt,
    completedAt = completedAt,
    idempotencyKey = idempotencyKey,
    receiptJson = receiptJson,
    blocksFollowing = blocksFollowing,
)

sealed interface ConflictResolution {
    data class KeepMine(val freshToken: Long) : ConflictResolution
    data object DropMine : ConflictResolution
}

sealed interface FailedResolution {
    data class Retry(val freshToken: Long? = null) : FailedResolution
    data object Drop : FailedResolution
}
