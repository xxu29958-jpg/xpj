package com.ticketbox.data.repository

import com.ticketbox.data.local.NotificationSnapshotDao
import com.ticketbox.data.local.NotificationSnapshotEntity
import com.ticketbox.data.local.PendingMutationEntity
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

internal class FakeNotificationSnapshotDao(private val originals: FakePendingMutationDao) : NotificationSnapshotDao {
    private val snapshots = mutableMapOf<String, NotificationSnapshotEntity>()
    private val admission = Mutex()
    override suspend fun notificationSnapshot(slotKey: String) = snapshots[slotKey]
    override suspend fun saveNotificationSnapshot(snapshot: NotificationSnapshotEntity) { snapshots[snapshot.slotKey] = snapshot }
    override suspend fun closeNotificationSnapshot(slotKey: String, deliveryKey: String) {
        snapshots[slotKey]?.takeIf { it.deliveryKey == deliveryKey }?.let { snapshots[slotKey] = it.copy(closed = true) }
    }
    override suspend fun notificationDelivery(key: String) = originals.rows.values.firstOrNull {
        it.type == com.ticketbox.data.local.PendingMutationType.CapturePaymentNotification.wireValue && it.idempotencyKey == key
    }
    override suspend fun acceptNotificationSnapshot(slotKey: String, deliveryKey: String,
        publish: suspend (NotificationSnapshotEntity?, PendingMutationEntity?) -> NotificationSnapshotEntity): Long =
        admission.withLock { super.acceptNotificationSnapshot(slotKey, deliveryKey, publish) }
}
