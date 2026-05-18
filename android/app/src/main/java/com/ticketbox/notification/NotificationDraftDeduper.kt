package com.ticketbox.notification

import com.ticketbox.domain.model.NotificationDraft

internal class NotificationDraftDeduper(
    private val clockMillis: () -> Long = { System.currentTimeMillis() },
    private val ttlMillis: Long = DEFAULT_TTL_MILLIS,
) {
    private val recentDraftKeys = LinkedHashMap<String, Long>()

    fun tryReserve(draft: NotificationDraft): Boolean {
        val now = clockMillis()
        val key = draft.dedupKey()
        synchronized(recentDraftKeys) {
            val iterator = recentDraftKeys.entries.iterator()
            while (iterator.hasNext()) {
                if (now - iterator.next().value > ttlMillis) {
                    iterator.remove()
                }
            }
            if (recentDraftKeys.containsKey(key)) return false
            recentDraftKeys[key] = now
            return true
        }
    }

    fun release(draft: NotificationDraft) {
        val key = draft.dedupKey()
        synchronized(recentDraftKeys) {
            recentDraftKeys.remove(key)
        }
    }

    private fun NotificationDraft.dedupKey(): String = listOf(
        source.apiValue,
        amountCents?.toString().orEmpty(),
        merchant.orEmpty(),
        expenseTime.orEmpty().take(16),
    ).joinToString("|")

    private companion object {
        const val DEFAULT_TTL_MILLIS = 30 * 60 * 1000L
    }
}
