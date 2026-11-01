package com.ticketbox.notification

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.provider.Settings
import android.service.notification.NotificationListenerService

object NotificationListenerStatus {
    fun reconnectIfEnabled(context: Context) {
        if (isEnabled(context)) {
            NotificationListenerService.requestRebind(ComponentName(context, TicketboxNotificationListenerService::class.java))
        }
    }

    fun isEnabled(context: Context): Boolean {
        val enabledListeners = Settings.Secure.getString(
            context.contentResolver,
            "enabled_notification_listeners",
        ) ?: return false
        return enabledListeners
            .split(':')
            .mapNotNull(ComponentName::unflattenFromString)
            .any { component ->
                component.packageName == context.packageName &&
                    component.className == TicketboxNotificationListenerService::class.java.name
            }
    }

    fun settingsIntent(): Intent = Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)
}
