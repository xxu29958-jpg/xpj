package com.ticketbox.domain.model

data class NotificationPreferences(
    val autoCaptureEnabled: Boolean = false,
    val pendingDraftReminders: Boolean = false,
    val largeAmountAlerts: Boolean = false,
    val recurringReminders: Boolean = false,
    val budgetOverspendAlerts: Boolean = false,
    // 构造已满 detekt LongParameterList 的 allowedConstructorParameters=6;
    // 再加开关前先想要不要折叠成子结构。
    val backupStaleAlerts: Boolean = false,
)
