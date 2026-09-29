package com.ticketbox.notification

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.Uri
import com.ticketbox.MainActivity

/** Data participates in PendingIntent identity; extras alone would let another task replace this one. */
internal fun notificationTaskPendingIntent(context: Context, task: NotificationTask): PendingIntent {
    val intent = Intent(context, MainActivity::class.java).apply {
        action = ACTION_NOTIFICATION_TASK
        data = Uri.Builder().scheme("ticketbox").authority("notification").appendPath(task.intentIdentity()).build()
        putStringArrayListExtra(EXTRA_NOTIFICATION_TASK, task.savedFields())
        flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP
    }
    return PendingIntent.getActivity(context, 0, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
}
