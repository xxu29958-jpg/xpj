package com.ticketbox.data.repository

data class BindServerResult(
    val confirmedRestoreFailed: Boolean = false,
)

interface ServerBindingRepository {
    fun hasActiveSession(): Boolean

    suspend fun bindServer(serverUrl: String, pairingCode: String): Result<BindServerResult>

    suspend fun resumePendingBinding(): Result<BindServerResult>? = null

    /** Returns null when the persisted session already has a complete identity. */
    suspend fun reconcileActiveSession(): Result<Unit>? = null

    suspend fun clearBinding()
}
