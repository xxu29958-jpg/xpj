package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.RuntimeWriteCompatibility
import com.ticketbox.data.remote.dto.toWriteCompatibility
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow

/** One session-scoped compatibility result gates both admission and background replay. */
internal class OutboxRuntimeCompatibility(private val guard: LedgerRequestGuard) {
    private val currentBlock = MutableStateFlow<OutboxWriteBlock?>(null)
    val writeBlock = currentBlock.asStateFlow()

    suspend fun refresh(): RuntimeWriteCompatibility = guard.guardedCall { api ->
        api.runtimeCompatibility().toWriteCompatibility().also { compatibility ->
            currentBlock.value = if (compatibility.conclusion == "owner_action_required") {
                OutboxWriteBlock.CURRENCY_ADOPTION_REQUIRED
            } else {
                null
            }
        }
    }

    fun clearWriteBlock() { currentBlock.value = null }
}
