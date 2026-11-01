package com.ticketbox.data.local

import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Transaction

/** Device source identity is independent of the currently selected financial principal. */
@Entity(tableName = "notification_snapshots")
data class NotificationSnapshotEntity(@PrimaryKey val slotKey: String, val deliveryKey: String,
    val postTimeMillis: Long, val cardsJson: String, val originalId: Long, val closed: Boolean = false)

@Dao
interface NotificationSnapshotDao {
    @Query("SELECT * FROM notification_snapshots WHERE slotKey = :slotKey")
    suspend fun notificationSnapshot(slotKey: String): NotificationSnapshotEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun saveNotificationSnapshot(snapshot: NotificationSnapshotEntity)

    @Query("UPDATE notification_snapshots SET closed = 1 WHERE slotKey = :slotKey AND deliveryKey = :deliveryKey")
    suspend fun closeNotificationSnapshot(slotKey: String, deliveryKey: String)

    @Query("SELECT * FROM pending_mutations WHERE type = 'capture_payment_notification' AND idempotencyKey = :key ORDER BY id LIMIT 1")
    suspend fun notificationDelivery(key: String): PendingMutationEntity?

    /** The source journal and any new Outbox original publish in the same Room transaction. */
    @Transaction
    suspend fun acceptNotificationSnapshot(slotKey: String, deliveryKey: String,
        publish: suspend (NotificationSnapshotEntity?, PendingMutationEntity?) -> NotificationSnapshotEntity): Long {
        val previous = notificationSnapshot(slotKey)
        val next = publish(previous, notificationDelivery(deliveryKey))
        if (previous == null || next.postTimeMillis >= previous.postTimeMillis) saveNotificationSnapshot(next)
        return next.originalId
    }
}
