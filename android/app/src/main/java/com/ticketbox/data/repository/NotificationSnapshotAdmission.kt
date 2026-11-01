package com.ticketbox.data.repository

import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.ticketbox.data.local.NotificationSnapshotEntity
import com.ticketbox.notification.ParsedNotificationCard

@JsonClass(generateAdapter = true)
internal data class NotificationCardIdentity(val fingerprint: String, val key: String)

internal data class NotificationSnapshotDelivery(val slotKey: String, val key: String, val postTimeMillis: Long)
internal data class NotificationSnapshotAdmission(val snapshot: NotificationSnapshotEntity, val intent: PendingMutationIntent?)

private val cardIdentities = Moshi.Builder().build().adapter<List<NotificationCardIdentity>>(
    Types.newParameterizedType(List::class.java, NotificationCardIdentity::class.java))

/** Match occurrences, not amounts: two identical lines always retain two event identities. */
internal fun planNotificationSnapshot(cards: List<ParsedNotificationCard>, delivery: NotificationSnapshotDelivery,
    previous: NotificationSnapshotEntity?, original: OutboxRow?): NotificationSnapshotAdmission {
    require(cards.isNotEmpty())
    if (previous?.deliveryKey == delivery.key) return NotificationSnapshotAdmission(previous, null)
    if (original != null) return retainedDelivery(cards, delivery, original)
    val old = if (previous == null || previous.closed) emptyList()
        else requireNotNull(cardIdentities.fromJson(previous.cardsJson))
    // A new standalone post is independent, even at the same price and in the same OS slot.
    val remaining = old.takeIf { cards.size > 1 || old.size > 1 }.orEmpty().toMutableList()
    val identities = cards.map { card ->
        remaining.firstOrNull { it.fingerprint == card.fingerprint }?.also { remaining.remove(it) }
    }.toMutableList()
    val freshIndices = identities.indices.filter { identities[it] == null }
    val fresh = freshIndices.map { cards[it].result }
    val intent = when (fresh.size) {
        0 -> null
        1 -> fresh.single().captureIntent(delivery.key)
        else -> fresh.captureBatchIntent(delivery.key)
    }
    val keys = intent?.let { captureKeys(requireNotNull(NotificationCaptureWire.payload.fromJson(it.payloadJson))) }.orEmpty()
    freshIndices.zip(keys).forEach { (index, key) -> identities[index] = NotificationCardIdentity(cards[index].fingerprint, key) }
    return NotificationSnapshotAdmission(NotificationSnapshotEntity(delivery.slotKey, delivery.key, delivery.postTimeMillis,
        cardIdentities.toJson(identities.map { requireNotNull(it) }), previous?.originalId ?: 0), intent)
}

private fun retainedDelivery(cards: List<ParsedNotificationCard>, delivery: NotificationSnapshotDelivery,
    original: OutboxRow): NotificationSnapshotAdmission {
    val capture = requireNotNull(original.notificationCapture())
    val keys = captureKeys(capture)
    // A changed interpretation cannot replace the first original. Only complete correspondence seeds overlap matching.
    val identities = if (keys.size == cards.size) cards.zip(keys).map { (card, key) -> NotificationCardIdentity(card.fingerprint, key) }
        else emptyList()
    return NotificationSnapshotAdmission(NotificationSnapshotEntity(delivery.slotKey, delivery.key, delivery.postTimeMillis,
        cardIdentities.toJson(identities), original.id), null)
}

private fun captureKeys(capture: NotificationCapturePayload) =
    if (capture.kind == "batch") capture.captures.map { it.notificationKey } else listOf(capture.notificationKey)
