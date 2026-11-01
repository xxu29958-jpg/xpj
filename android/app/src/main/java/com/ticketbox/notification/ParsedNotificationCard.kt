package com.ticketbox.notification

internal data class ParsedNotificationCard(val result: PaymentNotificationResult, val fingerprint: String)

/** Only a digest enters the identity journal; notification bodies and OS keys remain outside Room. */
private fun canonicalCard(text: String) = java.text.Normalizer.normalize(text, java.text.Normalizer.Form.NFKC)
    .filter { it.isLetterOrDigit() }

internal fun notificationCardFingerprint(packageName: String, card: String): String =
    notificationIdentityKey("card:${packageName.lowercase()}:${canonicalCard(card)}", 0)
