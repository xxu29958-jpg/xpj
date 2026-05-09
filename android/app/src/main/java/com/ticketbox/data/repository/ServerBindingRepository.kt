package com.ticketbox.data.repository

data class BindServerResult(
    val confirmedRestoreFailed: Boolean = false,
)

interface ServerBindingRepository {
    suspend fun bindServer(serverUrl: String, pairingCode: String): Result<BindServerResult>

    suspend fun clearBinding()
}
