package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.PairRequestDto
import kotlinx.coroutines.CancellationException
import java.time.Instant

internal class ExpenseBindingRepository(
    private val core: ExpenseRepositoryCore,
) : ServerBindingRepository {
    override suspend fun bindServer(serverUrl: String, pairingCode: String): Result<BindServerResult> {
        return core.errorHandler.safeCall(serverUrlHint = serverUrl) {
            val normalized = validateBindingInput(serverUrl, pairingCode)
            val pairResponse = core.apiProvider.unauthenticated(normalized).pairDevice(
                PairRequestDto(
                    pairingCode = pairingCode.trim(),
                    deviceName = core.deviceNameProvider(),
                    platform = "android",
                ),
            )
            core.sessionCoordinator.applyTransition(
                serverUrl = normalized,
                sessionToken = pairResponse.sessionToken,
                tokenExpiresAt = pairResponse.expiresAt,
                tokenSoftRefreshAfter = pairResponse.softRefreshAfter,
                identity = LedgerSessionIdentity(
                    accountName = pairResponse.accountName,
                    ledgerId = pairResponse.ledgerId,
                    ledgerName = pairResponse.ledgerName,
                    deviceName = pairResponse.deviceName,
                    role = pairResponse.role,
                    boundAt = Instant.now().toString(),
                ),
                cacheInvalidation = LedgerCacheInvalidation.AllLedgers,
                clearAvailableLedgers = true,
                markUnlocked = true,
            )
            val restoreFailed = try {
                core.syncConfirmedFromService(
                    service = core.api(normalized, pairResponse.sessionToken),
                    ledgerIdAtRequest = pairResponse.ledgerId,
                    replaceCache = true,
                )
                false
            } catch (error: Exception) {
                if (error is CancellationException) throw error
                logNetworkWarning("Confirmed restore failed after successful binding.", error)
                true
            }
            BindServerResult(confirmedRestoreFailed = restoreFailed)
        }
    }

    override suspend fun clearBinding() {
        core.clearBinding()
    }
}
