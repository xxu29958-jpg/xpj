package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.ExpenseDao
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.dto.DeviceRenameRequestDto
import com.ticketbox.data.remote.dto.LedgerCreateRequestDto
import com.ticketbox.data.remote.dto.LedgerDto
import com.ticketbox.data.remote.dto.ErrorDto
import com.ticketbox.data.remote.dto.MyDeviceDto
import com.ticketbox.data.remote.dto.PairingCodeCreateRequestDto
import com.ticketbox.data.remote.dto.PairingCodeResponseDto
import com.ticketbox.data.remote.dto.RecycleBinItemDto
import com.ticketbox.data.remote.dto.RecycleBinRestoreRequestDto
import com.ticketbox.data.remote.dto.InvitationAcceptRequestDto
import com.ticketbox.data.remote.dto.InvitationAcceptResponseDto
import com.ticketbox.data.remote.dto.InvitationCreateRequestDto
import com.ticketbox.data.remote.dto.InvitationCreateResponseDto
import com.ticketbox.data.remote.dto.InvitationPreviewRequestDto
import com.ticketbox.data.remote.dto.InvitationPreviewResponseDto
import com.ticketbox.data.remote.dto.LedgerAuditDto
import com.ticketbox.data.remote.dto.LedgerMemberDto
import com.ticketbox.data.remote.dto.LedgerMemberRoleUpdateRequestDto
import com.ticketbox.data.remote.dto.OwnerTransferResponseDto
import com.ticketbox.domain.model.AccountDevice
import com.ticketbox.domain.model.DevicePairingCode
import com.ticketbox.domain.model.FamilyInvitationCreated
import com.ticketbox.domain.model.FamilyMember
import com.ticketbox.domain.model.InvitationPreview
import com.ticketbox.domain.model.LedgerAuditEntry
import com.ticketbox.domain.model.LedgerSummary
import com.ticketbox.domain.model.OwnerTransferResult
import com.ticketbox.domain.model.RecycleBinItem
import com.ticketbox.domain.model.RecycleBinSnapshot
import com.ticketbox.domain.model.LEDGER_ROLE_MEMBER
import com.ticketbox.domain.model.LEDGER_ROLE_VIEWER
import com.ticketbox.domain.model.ledgerRoleCanModify
import com.ticketbox.security.LocalSessionStore
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import retrofit2.HttpException
import java.io.IOException
import java.time.Instant

/**
 * Repository for v0.4-alpha1 multi-ledger management.
 *
 * Owns the small surface that is **not** about expenses: listing the
 * ledgers an account belongs to, creating a new ledger, and switching
 * the active session token to a different ledger.
 *
 * Ownership is decided server-side; this repository never persists or
 * trusts a client-supplied role beyond display purposes.
 */
class LedgerRepository(
    private val settingsStore: TicketboxSettingsStore,
    private val expenseDao: ExpenseDao,
    private val sessionStore: LocalSessionStore,
    private val apiProvider: ApiServiceProvider,
    private val sessionCoordinator: LocalLedgerSessionCoordinator = LocalLedgerSessionCoordinator(
        settingsStore = settingsStore,
        sessionStore = sessionStore,
        expenseDao = expenseDao,
    ),
) {
    private val moshi: Moshi by lazy {
        Moshi.Builder()
            .add(KotlinJsonAdapterFactory())
            .build()
    }
    private val errorAdapter by lazy {
        moshi.adapter(ErrorDto::class.java)
    }
    private val ledgerListType by lazy {
        Types.newParameterizedType(
            List::class.java,
            LedgerDto::class.java,
        )
    }
    private val ledgerListAdapter by lazy {
        moshi.adapter<List<LedgerDto>>(ledgerListType)
    }
    private val switchLedgerMutex = Mutex()
    private val requestGuard = LedgerRequestGuard(apiProvider)
    private val enrollment = DeviceEnrollmentCoordinator(
        sessionStore = sessionStore,
        apiProvider = apiProvider,
        sessionCoordinator = sessionCoordinator,
    )

    private fun unauthenticatedApi() = apiProvider.unauthenticated(
        requireNotNull(apiProvider.currentSession()?.serverUrl) {
            "账本地址未绑定"
        },
    )

    suspend fun refreshLedgers(): Result<List<LedgerSummary>> = wrap {
        val bound = requestGuard.bind()
        val response = bound.call { it.listLedgers() }
        val summaries = response.ledgers.map { it.toSummary() }
        bound.requireStillActive()
        settingsStore.saveAvailableLedgersJson(ledgerListAdapter.toJson(response.ledgers))
        summaries.firstOrNull { it.ledgerId == bound.ledgerId }
            ?.let { persistCurrentRoleIfChanged(it.role, expectedLedgerId = bound.ledgerId) }
        summaries
    }

    fun cachedLedgers(): List<LedgerSummary> {
        val raw = settingsStore.availableLedgersJson()?.takeIf { it.isNotBlank() }
            ?: return emptyList()
        return runCatching {
            ledgerListAdapter.fromJson(raw)?.map { it.toSummary() } ?: emptyList()
        }.getOrElse { emptyList() }
    }

    fun currentAccountName(): String? = apiProvider.currentSession()?.identity?.accountName

    fun currentLedgerName(): String? = apiProvider.currentSession()?.identity?.ledgerName

    fun currentLedgerRole(): String? = apiProvider.currentLedgerRole()

    fun canModifyLedger(): Boolean = ledgerRoleCanModify(apiProvider.currentLedgerRole())

    fun activeLedgerId(): String? = apiProvider.currentLedgerId()

    suspend fun createLedger(name: String): Result<LedgerSummary> = wrap {
        val cleanName = name.trim()
        require(cleanName.isNotEmpty()) { "请填写账本名称。" }
        require(cleanName.length <= LEDGER_NAME_MAX_LEN) { "账本名称最多 60 个字。" }
        val dto = requestGuard.guardedCall { api ->
            api.createLedger(LedgerCreateRequestDto(name = cleanName))
        }
        // Refresh the cache so the new ledger appears in the picker.
        runCatching { refreshLedgers() }
        dto.toSummary()
    }

    /**
     * Switch the active session token to [ledgerId]. The previous token is
     * revoked server-side, so we must persist the freshly issued token
     * before doing any post-switch network calls. The local confirmed-cache
     * for the *new* ledger is wiped so the next sync repopulates it
     * exclusively with rows belonging to [ledgerId].
     */
    suspend fun switchLedger(ledgerId: String): Result<LedgerSummary> = wrap {
        switchLedgerMutex.withLock {
            val session = sessionCoordinator.currentSnapshot()
            val bound = requestGuard.bind(expectedLedgerId = session.activeLedgerId)
            val response = bound.call { api -> api.switchLedger(ledgerId) }
            val serverId = response.serverId.requireSessionProtocolId("服务器身份")
            val dataGeneration = response.dataGeneration.requireSessionProtocolId("数据代际")
            val accountPublicId = response.accountPublicId.requireSessionProtocolId("成员身份")
            val devicePublicId = response.devicePublicId.requireSessionProtocolId("设备身份")
            val applied = sessionCoordinator.applyTransitionIfCurrent(
                expectedSnapshot = session,
                transition = LedgerSessionTransition(
                    change = LocalSessionChange.SelectLedger,
                    serverId = serverId,
                    dataGeneration = dataGeneration,
                    sessionToken = response.sessionToken,
                    tokenExpiresAt = response.expiresAt,
                    tokenSoftRefreshAfter = response.softRefreshAfter,
                    identity = LedgerSessionIdentity(
                        accountPublicId = accountPublicId,
                        devicePublicId = devicePublicId,
                        accountName = response.accountName,
                        ledgerId = response.ledger.ledgerId,
                        ledgerName = response.ledger.name,
                        deviceName = response.deviceName,
                        role = response.ledger.role,
                        boundAt = apiProvider.currentSession()?.identity?.boundAt ?: Instant.now().toString(),
                    ),
                    cacheInvalidation = LedgerCacheInvalidation.TargetLedger,
                ),
            )
            if (!applied) {
                throw RepositoryException(LedgerRequestGuard.LEDGER_CHANGED_MESSAGE)
            }
            response.ledger.toSummary()
        }
    }

    suspend fun refreshFamilyMembers(ledgerId: String? = activeLedgerId()): Result<List<FamilyMember>> = wrap {
        val targetLedgerId = requireNotNull(ledgerId?.takeIf { it.isNotBlank() }) {
            "当前账本还没有准备好。"
        }
        val members = requestGuard.guardedCall(expectedLedgerId = targetLedgerId) { api ->
            api.ledgerMembers(targetLedgerId).members.map { it.toFamilyMember() }
        }
        members.firstOrNull { it.isSelf }?.let { persistSelfRoleIfChanged(it, expectedLedgerId = targetLedgerId) }
        members
    }

    suspend fun refreshFamilyAudit(
        ledgerId: String? = activeLedgerId(),
        limit: Int = AUDIT_DEFAULT_LIMIT,
    ): Result<List<LedgerAuditEntry>> = wrap {
        val targetLedgerId = requireActiveLedger(ledgerId)
        val safeLimit = limit.coerceIn(1, AUDIT_MAX_LIMIT)
        requestGuard.guardedCall(expectedLedgerId = targetLedgerId) { api ->
            api.ledgerAudit(targetLedgerId, safeLimit).items.map { it.toLedgerAuditEntry() }
        }
    }

    suspend fun updateFamilyMemberRole(
        memberId: Long,
        role: String,
        ledgerId: String? = activeLedgerId(),
    ): Result<FamilyMember> = wrap {
        val targetLedgerId = requireActiveLedger(ledgerId)
        val cleanRole = role.trim()
        require(cleanRole == LEDGER_ROLE_MEMBER || cleanRole == LEDGER_ROLE_VIEWER) {
            "成员角色只能是成员或只读。"
        }
        requestGuard.guardedCall(expectedLedgerId = targetLedgerId) { api ->
            api.updateLedgerMemberRole(
                ledgerId = targetLedgerId,
                memberId = memberId,
                request = LedgerMemberRoleUpdateRequestDto(role = cleanRole),
            ).toFamilyMember()
        }
    }

    /**
     * 轴7 发邀请(owner 级,后端 403 兜底;UI 已按角色隐藏只做体验)。返回的
     * [FamilyInvitationCreated.inviteToken] 是唯一一次明文——调用方负责当场展示/复制。
     * note / ttl_days 走后端默认(7 天),MVP 不在客户端暴露。
     */
    suspend fun createFamilyInvitation(
        role: String,
        ledgerId: String? = activeLedgerId(),
    ): Result<FamilyInvitationCreated> = wrap {
        val targetLedgerId = requireActiveLedger(ledgerId)
        val cleanRole = role.trim()
        // 与后端 Invitation.role 契约一致:owner 经显式 owner-transfer,不走邀请。
        require(cleanRole == LEDGER_ROLE_MEMBER || cleanRole == LEDGER_ROLE_VIEWER) {
            "邀请角色只能是成员或只读。"
        }
        requestGuard.guardedCall(expectedLedgerId = targetLedgerId) { api ->
            api.createInvitation(
                ledgerId = targetLedgerId,
                request = InvitationCreateRequestDto(role = cleanRole),
            ).toFamilyInvitationCreated()
        }
    }

    suspend fun disableFamilyMember(
        memberId: Long,
        ledgerId: String? = activeLedgerId(),
    ): Result<FamilyMember> = wrap {
        val targetLedgerId = requireActiveLedger(ledgerId)
        requestGuard.guardedCall(expectedLedgerId = targetLedgerId) { api ->
            api.disableLedgerMember(targetLedgerId, memberId).toFamilyMember()
        }
    }

    suspend fun transferOwner(
        memberId: Long,
        ledgerId: String? = activeLedgerId(),
    ): Result<OwnerTransferResult> = wrap {
        val targetLedgerId = requireActiveLedger(ledgerId)
        val response = requestGuard.guardedCall(expectedLedgerId = targetLedgerId) { api ->
            api.transferLedgerOwner(targetLedgerId, memberId)
        }
        val result = response.toOwnerTransferResult()
        persistSelfRoleIfChanged(result.previousOwner, expectedLedgerId = targetLedgerId)
        persistSelfRoleIfChanged(result.newOwner, expectedLedgerId = targetLedgerId)
        runCatching { refreshLedgers() }
        result
    }

    /**
     * issue #65 slice 6b: list the devices that can access [ledgerId]. Backend
     * (slice 6a) scopes to the active ledger + owner role (403 兜底); the UI
     * hides the screen for non-owners only as an experience nicety.
     */
    suspend fun refreshDevices(
        ledgerId: String? = activeLedgerId(),
    ): Result<List<AccountDevice>> = wrap {
        val targetLedgerId = requireActiveLedger(ledgerId)
        requestGuard.guardedCall(expectedLedgerId = targetLedgerId) { api ->
            api.ledgerDevices(targetLedgerId).devices.map { it.toAccountDevice() }
        }
    }

    suspend fun renameDevice(
        publicId: String,
        deviceName: String,
        ledgerId: String? = activeLedgerId(),
    ): Result<AccountDevice> = wrap {
        val targetLedgerId = requireActiveLedger(ledgerId)
        val cleanName = deviceName.trim()
        require(cleanName.isNotEmpty()) { "设备名称不能为空。" }
        requestGuard.guardedCall(expectedLedgerId = targetLedgerId) { api ->
            api.renameLedgerDevice(
                ledgerId = targetLedgerId,
                publicId = publicId,
                request = DeviceRenameRequestDto(deviceName = cleanName),
            ).toAccountDevice()
        }
    }

    suspend fun revokeDevice(
        publicId: String,
        ledgerId: String? = activeLedgerId(),
    ): Result<AccountDevice> = wrap {
        val targetLedgerId = requireActiveLedger(ledgerId)
        requestGuard.guardedCall(expectedLedgerId = targetLedgerId) { api ->
            api.revokeLedgerDevice(targetLedgerId, publicId).toAccountDevice()
        }
    }

    /**
     * issue #65 slice A: permanently remove an already-revoked device from the
     * ledger. The backend (204) re-asserts the revoked-first precondition; the
     * client surfaces "移除" only on already-revoked rows as an experience nicety.
     */
    suspend fun deleteDevice(
        publicId: String,
        ledgerId: String? = activeLedgerId(),
    ): Result<Unit> = wrap {
        val targetLedgerId = requireActiveLedger(ledgerId)
        requestGuard.guardedCall(expectedLedgerId = targetLedgerId) { api ->
            api.deleteLedgerDevice(targetLedgerId, publicId)
        }
    }

    /**
     * Mint a one-time code either for a new Device or for explicit recovery of
     * one existing Device owned by this Account.
     */
    suspend fun createDevicePairingCode(
        recoveryDevice: AccountDevice? = null,
        ledgerId: String? = activeLedgerId(),
    ): Result<DevicePairingCode> = wrap {
        val targetLedgerId = requireActiveLedger(ledgerId)
        requestGuard.guardedCall(expectedLedgerId = targetLedgerId) { api ->
            api.createLedgerDevicePairingCode(
                ledgerId = targetLedgerId,
                request = PairingCodeCreateRequestDto(
                    recoveryDevicePublicId = recoveryDevice?.publicId,
                ),
            ).toDevicePairingCode(recoveryDevice?.deviceName)
        }
    }

    suspend fun refreshRecycleBin(): Result<RecycleBinSnapshot> = wrap {
        val targetLedgerId = requireActiveLedger(activeLedgerId())
        val response = requestGuard.guardedCall(expectedLedgerId = targetLedgerId) { api ->
            api.recycleBin()
        }
        val items = response.items.map { it.toRecycleBinItem() }
        RecycleBinSnapshot(
            items = items,
            shortWindowCount = response.shortWindowCount.coerceIn(0, items.size),
        )
    }

    suspend fun restoreRecycleBinItem(item: RecycleBinItem): Result<String> = wrap {
        val targetLedgerId = requireActiveLedger(activeLedgerId())
        requestGuard.guardedCall(expectedLedgerId = targetLedgerId) { api ->
            api.restoreRecycleBinItem(
                RecycleBinRestoreRequestDto(
                    kind = item.kind,
                    resourceId = item.resourceId,
                    expectedRowVersion = item.expectedRowVersion,
                ),
            ).message
        }
    }

    /**
     * Preview a family-ledger invitation. [serverUrlOverride] is the cold-start
     * (unbound device) entry: the URL is normalized/validated through the same
     * [validateServerUrlInput] rules as pairing-code binding and the call goes
     * out unauthenticated against it. ``null`` keeps the historical behaviour:
     * the device must already be bound (otherwise "账本地址未绑定").
     */
    suspend fun previewInvitation(
        inviteToken: String,
        serverUrlOverride: String? = null,
    ): Result<InvitationPreview> = wrap {
        val cleanToken = inviteToken.trim()
        require(cleanToken.isNotEmpty()) { "请粘贴邀请明文。" }
        val api = serverUrlOverride
            ?.let { apiProvider.unauthenticated(validateServerUrlInput(it)) }
            ?: unauthenticatedApi()
        api.previewInvitation(
            InvitationPreviewRequestDto(inviteToken = cleanToken),
        ).toInvitationPreview()
    }

    /**
     * v0.4-beta1: accept a family-ledger invitation.
     *
     * An unbound installation persists a recoverable enrollment attempt before
     * consuming the invitation. An already bound installation keeps its
     * Account, Device, token and session generation; the server only activates
     * membership and the client selects the joined ledger.
     *
     * [serverUrlOverride] is the cold-start (unbound device) join entry. It is
     * validated through the bind-screen URL rules, the accept goes out
     * **unauthenticated** (never attach a stored token to a caller-supplied
     * host), and the success transition additionally persists the server URL
     * and marks the device unlocked — mirroring pairing-code binding so the
     * freshly joined member is not stranded on the unlock screen.
     */
    suspend fun acceptInvitation(
        inviteToken: String,
        accountName: String,
        deviceName: String,
        serverUrlOverride: String? = null,
    ): Result<LedgerSummary> = wrap {
        val cleanToken = inviteToken.trim()
        require(cleanToken.isNotEmpty()) { "请粘贴邀请明文。" }
        val cleanAccount = accountName.trim()
        require(cleanAccount.isNotEmpty()) { "请填写你的显示名。" }
        require(cleanAccount.length <= 120) { "显示名最多 120 个字。" }
        val cleanDevice = deviceName.trim()
        require(cleanDevice.isNotEmpty()) { "请填写设备名。" }
        require(cleanDevice.length <= 120) { "设备名最多 120 个字。" }
        val session = sessionCoordinator.currentSnapshot()
        val joiningUnbound = session.sessionToken == null
        require(joiningUnbound || serverUrlOverride == null) {
            "已绑定设备不能通过邀请覆盖当前服务器，请先确认当前账号。"
        }
        val serverUrl = resolvedInvitationServerUrl(serverUrlOverride, session)
        val joinedIdentity = if (joiningUnbound) {
            enrollment.acceptInvitation(
                serverUrl = serverUrl,
                inviteToken = cleanToken,
                accountName = cleanAccount,
                deviceName = cleanDevice,
            )
        } else {
            val response = requestGuard.guardedCall(expectedLedgerId = session.activeLedgerId) { api ->
                api.acceptInvitation(
                    InvitationAcceptRequestDto(
                        inviteToken = cleanToken,
                        accountName = cleanAccount,
                        deviceName = cleanDevice,
                    ),
                )
            }
            val current = requireNotNull(sessionStore.currentSession())
            val applied = sessionCoordinator.applyTransitionIfCurrent(
                expectedSnapshot = session,
                transition = response.toLedgerSelectionTransition(current.identity.boundAt),
            )
            if (!applied) {
                throw RepositoryException(LedgerRequestGuard.LEDGER_CHANGED_MESSAGE)
            }
            response.toLedgerSessionIdentity(current.identity.boundAt)
        }
        // Refresh the ledger list so the picker shows the joined ledger.
        runCatching { refreshLedgers() }
        LedgerSummary(
            ledgerId = joinedIdentity.ledgerId,
            name = joinedIdentity.ledgerName,
            role = joinedIdentity.role,
            isDefault = false,
            createdAt = null,
            archivedAt = null,
        )
    }

    /** Override (cold-start join) goes through the shared bind-screen URL
     *  rules; otherwise the device's persisted binding is the only source. */
    private fun resolvedInvitationServerUrl(
        serverUrlOverride: String?,
        session: LedgerSessionSnapshot,
    ): String {
        if (serverUrlOverride != null) return validateServerUrlInput(serverUrlOverride)
        return requireNotNull(session.serverUrl?.takeIf { it.isNotBlank() }) {
            "Ledger server is not bound."
        }
    }

    private suspend fun <T> wrap(block: suspend () -> T): Result<T> {
        return try {
            Result.success(withContext(Dispatchers.IO) { block() })
        } catch (error: HttpException) {
            val body = error.response()?.errorBody()?.string()
            val parsed = body
                ?.let { runCatching { errorAdapter.fromJson(it) }.getOrNull() }
            val message = parsed
                ?.let { backendErrorUserMessage(it.error, it.message) }
                ?: defaultHttpMessage(error.code())
            Result.failure(RepositoryException(message))
        } catch (error: IOException) {
            Result.failure(RepositoryException("网络连接失败，请检查电脑端服务。"))
        } catch (error: RepositoryException) {
            Result.failure(error)
        } catch (error: IllegalArgumentException) {
            Result.failure(RepositoryException(error.message ?: "请求参数不正确。"))
        } catch (error: RuntimeException) {
            if (error is CancellationException) throw error
            Result.failure(RepositoryException(error.message ?: "操作失败。"))
        }
    }

    private fun defaultHttpMessage(code: Int): String = when (code) {
        401, 403 -> "绑定已失效，请重新绑定账本。"
        404 -> "账本不存在。"
        else -> "操作失败（$code），请稍后再试。"
    }

    private fun requireActiveLedger(ledgerId: String?): String {
        return requireNotNull(ledgerId?.takeIf { it.isNotBlank() }) {
            "当前账本还没有准备好。"
        }
    }

    private suspend fun persistSelfRoleIfChanged(member: FamilyMember, expectedLedgerId: String) {
        if (!member.isSelf) return
        persistCurrentRoleIfChanged(member.role, expectedLedgerId)
    }

    private suspend fun persistCurrentRoleIfChanged(role: String, expectedLedgerId: String) {
        val session = apiProvider.currentSession() ?: return
        if (session.identity.ledgerId != expectedLedgerId) return
        if (role == session.identity.role) return
        sessionCoordinator.applyTransition(
            LedgerSessionTransition(
                change = LocalSessionChange.RefreshProjection,
                identity = LedgerSessionIdentity(
                    accountPublicId = session.identity.accountPublicId,
                    devicePublicId = session.identity.devicePublicId,
                    accountName = session.identity.accountName,
                    ledgerId = session.identity.ledgerId,
                    ledgerName = session.identity.ledgerName,
                    deviceName = session.identity.deviceName,
                    role = role,
                    boundAt = session.identity.boundAt,
                ),
            ),
        )
    }

    private companion object {
        const val LEDGER_NAME_MAX_LEN = 60
        const val AUDIT_DEFAULT_LIMIT = 50
        const val AUDIT_MAX_LIMIT = 200
    }
}

private fun LedgerDto.toSummary(): LedgerSummary = LedgerSummary(
    ledgerId = ledgerId,
    name = name,
    role = role,
    isDefault = isDefault,
    createdAt = createdAt,
    archivedAt = archivedAt,
)

internal fun LedgerMemberDto.toFamilyMember(): FamilyMember = FamilyMember(
    memberId = memberId,
    accountId = accountId,
    accountPublicId = accountPublicId,
    displayName = accountName.ifBlank { "未命名成员" },
    role = role,
    joinedAt = createdAt,
    disabledAt = disabledAt,
    isSelf = isSelf,
)

internal fun LedgerAuditDto.toLedgerAuditEntry(): LedgerAuditEntry = LedgerAuditEntry(
    publicId = publicId,
    action = action,
    actorName = actorAccountName?.takeIf { it.isNotBlank() },
    targetName = targetAccountName?.takeIf { it.isNotBlank() },
    targetMemberId = targetMemberId,
    previousRole = previousRole?.takeIf { it.isNotBlank() },
    newRole = newRole?.takeIf { it.isNotBlank() },
    result = result,
    createdAt = createdAt,
)

internal fun MyDeviceDto.toAccountDevice(): AccountDevice = AccountDevice(
    publicId = publicId,
    deviceName = deviceName.ifBlank { "未命名设备" },
    platform = platform,
    lastSeenAt = lastSeenAt,
    createdAt = createdAt,
    revokedAt = revokedAt,
    isCurrent = isCurrent,
)

private fun PairingCodeResponseDto.toDevicePairingCode(
    recoveryDeviceName: String?,
): DevicePairingCode = DevicePairingCode(
    pairingCode = pairingCode,
    ledgerName = ledgerName,
    expiresAt = expiresAt,
    recoveryDeviceName = recoveryDeviceName,
)

private fun RecycleBinItemDto.toRecycleBinItem(): RecycleBinItem = RecycleBinItem(
    kind = kind,
    kindLabel = kindLabel,
    resourceId = resourceId,
    title = title.ifBlank { kindLabel },
    detail = detail,
    removedAt = removedAt,
    retentionLabel = retentionLabel,
    expectedRowVersion = expectedRowVersion,
)

private fun InvitationPreviewResponseDto.toInvitationPreview(): InvitationPreview = InvitationPreview(
    ledgerId = ledgerId,
    ledgerName = ledgerName,
    role = role,
    expiresAt = expiresAt,
)

private fun InvitationAcceptResponseDto.toLedgerSelectionTransition(
    boundAt: String,
): LedgerSessionTransition = LedgerSessionTransition(
    change = LocalSessionChange.SelectLedger,
    serverId = serverId.requireSessionProtocolId("服务器身份"),
    dataGeneration = dataGeneration.requireSessionProtocolId("数据代际"),
    identity = toLedgerSessionIdentity(boundAt),
    cacheInvalidation = LedgerCacheInvalidation.TargetLedger,
)

private fun InvitationAcceptResponseDto.toLedgerSessionIdentity(boundAt: String) =
    LedgerSessionIdentity(
        accountPublicId = accountPublicId.requireSessionProtocolId("成员身份"),
        devicePublicId = devicePublicId.requireSessionProtocolId("设备身份"),
        accountName = accountName,
        ledgerId = ledgerId,
        ledgerName = ledgerName,
        deviceName = deviceName,
        role = role,
        boundAt = boundAt,
    )

private fun InvitationCreateResponseDto.toFamilyInvitationCreated(): FamilyInvitationCreated =
    FamilyInvitationCreated(
        inviteToken = inviteToken,
        role = invitation.role,
        expiresAt = invitation.expiresAt,
    )

private fun OwnerTransferResponseDto.toOwnerTransferResult(): OwnerTransferResult = OwnerTransferResult(
    previousOwner = previousOwner.toFamilyMember(),
    newOwner = newOwner.toFamilyMember(),
)
