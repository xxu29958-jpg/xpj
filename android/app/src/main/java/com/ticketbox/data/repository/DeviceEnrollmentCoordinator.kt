package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.InvitationAcceptRequestDto
import com.ticketbox.data.remote.dto.InvitationAcceptResponseDto
import com.ticketbox.data.remote.dto.PairRequestDto
import com.ticketbox.data.remote.dto.PairResponseDto
import com.ticketbox.security.DeviceEnrollmentIntent
import com.ticketbox.security.LocalSessionStore
import com.ticketbox.security.PendingDeviceEnrollment
import com.ticketbox.security.StoredSessionToken
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.time.Instant

/** Process-death-safe authority boundary for first-device session enrollment. */
internal class DeviceEnrollmentCoordinator(
    private val sessionStore: LocalSessionStore,
    private val apiProvider: ApiServiceProvider,
    private val sessionCoordinator: LocalLedgerSessionCoordinator,
) {
    private val mutex = Mutex()

    suspend fun pairDevice(
        serverUrl: String,
        pairingCode: String,
        deviceName: String,
    ): LedgerSessionIdentity = mutex.withLock {
        requireUnbound()
        val normalized = validateBindingInput(serverUrl, pairingCode)
        complete(
            sessionStore.beginOrReuseDeviceEnrollment(
                DeviceEnrollmentIntent.Pairing(
                    serverUrl = normalized,
                    pairingCode = pairingCode.trim(),
                    deviceName = deviceName,
                ),
            ),
        )
    }

    suspend fun acceptInvitation(
        serverUrl: String,
        inviteToken: String,
        accountName: String,
        deviceName: String,
    ): LedgerSessionIdentity = mutex.withLock {
        requireUnbound()
        complete(
            sessionStore.beginOrReuseDeviceEnrollment(
                DeviceEnrollmentIntent.Invitation(
                    serverUrl = validateServerUrlInput(serverUrl),
                    inviteToken = inviteToken,
                    accountName = accountName,
                    deviceName = deviceName,
                ),
            ),
        )
    }

    suspend fun resumePending(): LedgerSessionIdentity? = mutex.withLock {
        sessionStore.pendingDeviceEnrollment()?.let { complete(it) }
    }

    private suspend fun complete(attempt: PendingDeviceEnrollment): LedgerSessionIdentity {
        requireUnbound()
        val transition = when (val intent = attempt.intent) {
            is DeviceEnrollmentIntent.Pairing -> pair(attempt, intent)
            is DeviceEnrollmentIntent.Invitation -> accept(attempt, intent)
        }
        sessionCoordinator.applyTransition(transition)
        return transition.identity
    }

    private fun requireUnbound() {
        if (sessionStore.currentSession() != null) {
            throw RepositoryException("当前设备已有登录身份，不能直接覆盖；请使用加入账本或先明确退出。")
        }
    }

    private suspend fun pair(
        attempt: PendingDeviceEnrollment,
        intent: DeviceEnrollmentIntent.Pairing,
    ): LedgerSessionTransition {
        val response = apiProvider.unauthenticated(intent.serverUrl).pairDevice(
            PairRequestDto(
                pairingCode = intent.pairingCode,
                pairingAttemptId = attempt.attemptId,
                pairingAttemptSecret = attempt.attemptSecret,
                deviceName = intent.deviceName,
                platform = "android",
            ),
        )
        requireMatchingAttempt(response.pairingAttemptId, attempt.attemptId)
        return response.toEnrollmentContract().toTransition(intent.serverUrl, attempt.attemptId)
    }

    private suspend fun accept(
        attempt: PendingDeviceEnrollment,
        intent: DeviceEnrollmentIntent.Invitation,
    ): LedgerSessionTransition {
        val response = apiProvider.unauthenticated(intent.serverUrl).acceptInvitation(
            InvitationAcceptRequestDto(
                inviteToken = intent.inviteToken,
                accountName = intent.accountName,
                deviceName = intent.deviceName,
                enrollmentAttemptId = attempt.attemptId,
                enrollmentAttemptSecret = attempt.attemptSecret,
            ),
        )
        requireMatchingAttempt(response.enrollmentAttemptId, attempt.attemptId)
        return response.toEnrollmentContract().toTransition(intent.serverUrl, attempt.attemptId)
    }
}

private fun requireMatchingAttempt(actual: String?, expected: String) {
    if (actual != expected) {
        throw RepositoryException("服务器响应与当前登记请求不一致，未保存任何凭据，请重试。")
    }
}

private data class EnrollmentSessionContract(
    val serverId: String,
    val dataGeneration: String,
    val credential: StoredSessionToken,
    val identity: LedgerSessionIdentity,
)

private fun PairResponseDto.toEnrollmentContract(): EnrollmentSessionContract =
    EnrollmentSessionContract(
        serverId = serverId.requireSessionProtocolId("服务器身份"),
        dataGeneration = dataGeneration.requireSessionProtocolId("数据代际"),
        credential = StoredSessionToken(sessionToken, expiresAt, softRefreshAfter),
        identity = LedgerSessionIdentity(
            accountPublicId = accountPublicId.requireSessionProtocolId("成员身份"),
            devicePublicId = devicePublicId.requireSessionProtocolId("设备身份"),
            accountName = accountName,
            ledgerId = ledgerId,
            ledgerName = ledgerName,
            deviceName = deviceName,
            role = role,
            boundAt = Instant.now().toString(),
        ),
    )

private fun InvitationAcceptResponseDto.toEnrollmentContract(): EnrollmentSessionContract =
    EnrollmentSessionContract(
        serverId = serverId.requireSessionProtocolId("服务器身份"),
        dataGeneration = dataGeneration.requireSessionProtocolId("数据代际"),
        credential = StoredSessionToken(sessionToken, expiresAt, softRefreshAfter),
        identity = LedgerSessionIdentity(
            accountPublicId = accountPublicId.requireSessionProtocolId("成员身份"),
            devicePublicId = devicePublicId.requireSessionProtocolId("设备身份"),
            accountName = accountName,
            ledgerId = ledgerId,
            ledgerName = ledgerName,
            deviceName = deviceName,
            role = role,
            boundAt = Instant.now().toString(),
        ),
    )

private fun EnrollmentSessionContract.toTransition(
    serverUrl: String,
    attemptId: String,
): LedgerSessionTransition = LedgerSessionTransition(
    change = LocalSessionChange.EstablishSession,
    serverId = serverId,
    dataGeneration = dataGeneration,
    serverUrl = serverUrl,
    sessionToken = credential.token,
    tokenExpiresAt = credential.expiresAt,
    tokenSoftRefreshAfter = credential.softRefreshAfter,
    identity = identity,
    cacheInvalidation = LedgerCacheInvalidation.AllLedgers,
    clearAvailableLedgers = true,
    markUnlocked = true,
    completedEnrollmentAttemptId = attemptId,
)
