package com.ticketbox.domain.model

data class NotificationPreferences(
    val pendingDraftReminders: Boolean = false,
    val largeAmountAlerts: Boolean = false,
    val recurringReminders: Boolean = false,
)
