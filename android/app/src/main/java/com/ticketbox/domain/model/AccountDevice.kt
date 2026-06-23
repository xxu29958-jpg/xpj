package com.ticketbox.domain.model

/**
 * issue #65 slice 6b: a device that can access the active ledger, shown on the
 * "My Devices" screen. [publicId] is the server UUID (never an internal id, §3);
 * [isCurrent] marks the device this session runs on (its revoke affordance is
 * hidden). [isRevoked] derives from [revokedAt].
 */
data class AccountDevice(
    val publicId: String,
    val deviceName: String,
    val platform: String,
    val lastSeenAt: String?,
    val createdAt: String?,
    val revokedAt: String?,
    val isCurrent: Boolean,
) {
    val isRevoked: Boolean
        get() = !revokedAt.isNullOrBlank()
}

/**
 * issue #65 slice 6b: a freshly minted device pairing code (the "add a device"
 * action). The plaintext [pairingCode] is returned ONCE — the screen shows it for
 * the user to enter on the new device (which then pairs via the existing bind
 * flow); the server stores only its hash.
 */
data class DevicePairingCode(
    val pairingCode: String,
    val ledgerName: String,
    val expiresAt: String,
)
