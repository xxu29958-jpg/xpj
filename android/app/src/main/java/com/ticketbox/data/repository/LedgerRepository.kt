package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.ExpenseDao
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.LedgerCreateRequestDto
import com.ticketbox.data.remote.dto.LedgerDto
import com.ticketbox.data.remote.dto.ErrorDto
import com.ticketbox.data.remote.dto.InvitationAcceptRequestDto
import com.ticketbox.data.remote.dto.InvitationPreviewRequestDto
import com.ticketbox.data.remote.dto.InvitationPreviewResponseDto
import com.ticketbox.data.remote.dto.LedgerAuditDto
import com.ticketbox.data.remote.dto.LedgerMemberDto
import com.ticketbox.data.remote.dto.LedgerMemberRoleUpdateRequestDto
import com.ticketbox.data.remote.dto.OwnerTransferResponseDto
import com.ticketbox.domain.model.FamilyMember
import com.ticketbox.domain.model.InvitationPreview
import com.ticketbox.domain.model.LedgerAuditEntry
import com.ticketbox.domain.model.LedgerSummary
import com.ticketbox.domain.model.OwnerTransferResult
import com.ticketbox.domain.model.LEDGER_ROLE_MEMBER
import com.ticketbox.domain.model.LEDGER_ROLE_VIEWER
import com.ticketbox.security.SessionTokenStore
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
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
    private val apiClient: ApiServiceFactory,
    private val settingsStore: TicketboxSettingsStore,
    private val tokenStore: SessionTokenStore,
    private val expenseDao: ExpenseDao,
    private val apiProvider: ApiServiceProvider = ApiServiceProvider(apiClient, settingsStore, tokenStore),
) {
    private val moshi: Moshi = Moshi.Builder()
        .add(KotlinJsonAdapterFactory())
        .build()
    private val errorAdapter = moshi.adapter(ErrorDto::class.java)
    private val ledgerListType = Types.newParameterizedType(
        List::class.java,
        LedgerDto::class.java,
    )
    private val ledgerListAdapter = moshi.adapter<List<LedgerDto>>(ledgerListType)

    private fun api() = apiProvider.current()

    suspend fun refreshLedgers(): Result<List<LedgerSummary>> = wrap {
        val response = api().listLedgers()
        val summaries = response.ledgers.map { it.toSummary() }
        settingsStore.saveAvailableLedgersJson(ledgerListAdapter.toJson(response.ledgers))
        settingsStore.activeLedgerId()
            ?.let { activeId ->
                summaries.firstOrNull { it.ledgerId == activeId }
                    ?.let { persistCurrentRoleIfChanged(it.role, expectedLedgerId = activeId) }
            }
        summaries
    }

    fun cachedLedgers(): List<LedgerSummary> {
        val raw = settingsStore.availableLedgersJson()?.takeIf { it.isNotBlank() }
            ?: return emptyList()
        return runCatching {
            ledgerListAdapter.fromJson(raw)?.map { it.toSummary() } ?: emptyList()
        }.getOrElse { emptyList() }
    }

    fun currentAccountName(): String? = settingsStore.accountName()

    fun currentLedgerName(): String? = settingsStore.activeLedgerName()
        ?: settingsStore.ledgerName()

    fun currentLedgerRole(): String? = settingsStore.role()

    fun activeLedgerId(): String? = settingsStore.activeLedgerId()

    suspend fun createLedger(name: String): Result<LedgerSummary> = wrap {
        val cleanName = name.trim()
        require(cleanName.isNotEmpty()) { "请填写账本名称。" }
        require(cleanName.length <= LEDGER_NAME_MAX_LEN) { "账本名称最多 60 个字。" }
        val dto = api().createLedger(LedgerCreateRequestDto(name = cleanName))
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
        val response = api().switchLedger(ledgerId)
        // Persist the new token *first*; the old one is now revoked.
        tokenStore.saveToken(response.sessionToken)
        settingsStore.saveIdentity(
            accountName = response.accountName,
            ledgerId = response.ledger.ledgerId,
            ledgerName = response.ledger.name,
            deviceName = response.deviceName,
            role = response.ledger.role,
            boundAt = settingsStore.boundAt() ?: Instant.now().toString(),
        )
        // Wipe stale cache for the target ledger so the upcoming sync
        // produces a clean view.
        expenseDao.clearForLedger(response.ledger.ledgerId)
        response.ledger.toSummary()
    }

    suspend fun refreshFamilyMembers(ledgerId: String? = activeLedgerId()): Result<List<FamilyMember>> = wrap {
        val targetLedgerId = requireNotNull(ledgerId?.takeIf { it.isNotBlank() }) {
            "当前账本还没有准备好。"
        }
        val members = api().ledgerMembers(targetLedgerId).members.map { it.toFamilyMember() }
        members.firstOrNull { it.isSelf }?.let { persistSelfRoleIfChanged(it, expectedLedgerId = targetLedgerId) }
        members
    }

    suspend fun refreshFamilyAudit(
        ledgerId: String? = activeLedgerId(),
        limit: Int = AUDIT_DEFAULT_LIMIT,
    ): Result<List<LedgerAuditEntry>> = wrap {
        val targetLedgerId = requireActiveLedger(ledgerId)
        val safeLimit = limit.coerceIn(1, AUDIT_MAX_LIMIT)
        api().ledgerAudit(targetLedgerId, safeLimit).items.map { it.toLedgerAuditEntry() }
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
        api().updateLedgerMemberRole(
            ledgerId = targetLedgerId,
            memberId = memberId,
            request = LedgerMemberRoleUpdateRequestDto(role = cleanRole),
        ).toFamilyMember()
    }

    suspend fun disableFamilyMember(
        memberId: Long,
        ledgerId: String? = activeLedgerId(),
    ): Result<FamilyMember> = wrap {
        val targetLedgerId = requireActiveLedger(ledgerId)
        api().disableLedgerMember(targetLedgerId, memberId).toFamilyMember()
    }

    suspend fun transferOwner(
        memberId: Long,
        ledgerId: String? = activeLedgerId(),
    ): Result<OwnerTransferResult> = wrap {
        val targetLedgerId = requireActiveLedger(ledgerId)
        val response = api().transferLedgerOwner(targetLedgerId, memberId)
        val result = response.toOwnerTransferResult()
        persistSelfRoleIfChanged(result.previousOwner, expectedLedgerId = targetLedgerId)
        persistSelfRoleIfChanged(result.newOwner, expectedLedgerId = targetLedgerId)
        runCatching { refreshLedgers() }
        result
    }

    suspend fun previewInvitation(inviteToken: String): Result<InvitationPreview> = wrap {
        val cleanToken = inviteToken.trim()
        require(cleanToken.isNotEmpty()) { "请粘贴邀请明文。" }
        api().previewInvitation(
            InvitationPreviewRequestDto(inviteToken = cleanToken),
        ).toInvitationPreview()
    }

    /**
     * v0.4-beta1: accept a family-ledger invitation.
     *
     * Posts the plain ``invite_token`` to the public
     * ``/api/invitations/accept`` endpoint; on success the server creates a
     * brand-new Account + Device + LedgerMember row and issues a session
     * token. The caller MUST already be unbound or willing to overwrite the
     * current binding — accept replaces the active session token, identity,
     * and active ledger. The local confirmed-cache for the joined ledger is
     * wiped so the next sync produces a clean view.
     */
    suspend fun acceptInvitation(
        inviteToken: String,
        accountName: String,
        deviceName: String,
    ): Result<LedgerSummary> = wrap {
        val cleanToken = inviteToken.trim()
        require(cleanToken.isNotEmpty()) { "请粘贴邀请明文。" }
        val cleanAccount = accountName.trim()
        require(cleanAccount.isNotEmpty()) { "请填写你的显示名。" }
        require(cleanAccount.length <= 120) { "显示名最多 120 个字。" }
        val cleanDevice = deviceName.trim()
        require(cleanDevice.isNotEmpty()) { "请填写设备名。" }
        require(cleanDevice.length <= 120) { "设备名最多 120 个字。" }
        val response = api().acceptInvitation(
            InvitationAcceptRequestDto(
                inviteToken = cleanToken,
                accountName = cleanAccount,
                deviceName = cleanDevice,
            ),
        )
        // Persist the new token *first*; any prior token is now stale.
        tokenStore.saveToken(response.sessionToken)
        settingsStore.saveIdentity(
            accountName = response.accountName,
            ledgerId = response.ledgerId,
            ledgerName = response.ledgerName,
            deviceName = response.deviceName,
            role = response.role,
            boundAt = java.time.Instant.now().toString(),
        )
        // Wipe stale cache so the new ledger view starts clean.
        expenseDao.clearForLedger(response.ledgerId)
        // Refresh the ledger list so the picker shows the joined ledger.
        runCatching { refreshLedgers() }
        LedgerSummary(
            ledgerId = response.ledgerId,
            name = response.ledgerName,
            role = response.role,
            isDefault = false,
            createdAt = null,
            archivedAt = null,
        )
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

    private fun persistSelfRoleIfChanged(member: FamilyMember, expectedLedgerId: String) {
        if (!member.isSelf) return
        persistCurrentRoleIfChanged(member.role, expectedLedgerId)
    }

    private fun persistCurrentRoleIfChanged(role: String, expectedLedgerId: String) {
        if (settingsStore.activeLedgerId() != expectedLedgerId) return
        if (role == settingsStore.role()) return
        val accountName = settingsStore.accountName() ?: return
        val ledgerId = settingsStore.activeLedgerId() ?: return
        val ledgerName = settingsStore.activeLedgerName() ?: settingsStore.ledgerName() ?: return
        val deviceName = settingsStore.deviceName() ?: return
        settingsStore.saveIdentity(
            accountName = accountName,
            ledgerId = ledgerId,
            ledgerName = ledgerName,
            deviceName = deviceName,
            role = role,
            boundAt = settingsStore.boundAt() ?: Instant.now().toString(),
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

private fun InvitationPreviewResponseDto.toInvitationPreview(): InvitationPreview = InvitationPreview(
    ledgerId = ledgerId,
    ledgerName = ledgerName,
    role = role,
    expiresAt = expiresAt,
)

private fun OwnerTransferResponseDto.toOwnerTransferResult(): OwnerTransferResult = OwnerTransferResult(
    previousOwner = previousOwner.toFamilyMember(),
    newOwner = newOwner.toFamilyMember(),
)
