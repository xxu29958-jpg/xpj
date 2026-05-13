package com.ticketbox.notification

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.provider.Settings

object NotificationListenerStatus {
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
