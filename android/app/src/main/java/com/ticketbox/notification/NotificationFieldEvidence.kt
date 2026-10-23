package com.ticketbox.notification

/** Only extracted field spans enter the retained command; no full notification body. */
data class NotificationFieldFragment(val field: String, val literal: String)
data class NotificationFieldEvidence(val fragments: List<NotificationFieldFragment>, val truncated: Boolean = false)
