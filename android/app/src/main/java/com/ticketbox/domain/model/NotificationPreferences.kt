package com.ticketbox.domain.model

data class NotificationPreferences(
    val autoCaptureEnabled: Boolean = false,
    val pendingDraftReminders: Boolean = false,
    val largeAmountAlerts: Boolean = false,
    val recurringReminders: Boolean = false,
)
