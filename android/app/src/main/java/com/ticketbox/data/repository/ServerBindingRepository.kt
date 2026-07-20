package com.ticketbox.data.repository

data class BindServerResult(
    val confirmedRestoreFailed: Boolean = false,
)

interface ServerBindingRepository {
    fun hasActiveSession(): Boolean

    fun isBusinessSessionReady(): Boolean

    fun hasPendingBinding(): Boolean

    suspend fun bindServer(serverUrl: String, pairingCode: String): Result<BindServerResult>

    suspend fun resumePendingBinding(): Result<BindServerResult>? = null

    suspend fun abandonPendingBinding(): Boolean

    /** Returns null when the persisted session already has a complete identity. */
    suspend fun reconcileActiveSession(): Result<Unit>? = null

    suspend fun clearBinding()
}
