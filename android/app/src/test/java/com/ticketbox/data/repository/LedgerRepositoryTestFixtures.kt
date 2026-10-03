package com.ticketbox.data.repository

import com.ticketbox.data.local.ExpenseDao
import com.ticketbox.data.local.ExpenseEntity
import com.ticketbox.data.local.ExpenseOffsetStreamEntity
import com.ticketbox.data.local.PersistedLedgerIdentity
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.InvitationAcceptRequestDto
import com.ticketbox.data.remote.dto.InvitationAcceptResponseDto
import com.ticketbox.data.remote.dto.InvitationPreviewRequestDto
import com.ticketbox.data.remote.dto.InvitationPreviewResponseDto
import com.ticketbox.data.remote.dto.LedgerAuditListResponseDto
import com.ticketbox.data.remote.dto.LedgerCreateRequestDto
import com.ticketbox.data.remote.dto.LedgerDto
import com.ticketbox.data.remote.dto.LedgerListResponseDto
import com.ticketbox.data.remote.dto.LedgerMemberDto
import com.ticketbox.data.remote.dto.LedgerMemberListResponseDto
import com.ticketbox.data.remote.dto.LedgerMemberRoleUpdateRequestDto
import com.ticketbox.data.remote.dto.LedgerSwitchResponseDto
import com.ticketbox.data.remote.dto.OwnerTransferResponseDto
import com.ticketbox.data.remote.dto.RecurringItemDto
import com.ticketbox.security.LocalSessionIdentity
import com.ticketbox.domain.model.BackgroundSettings
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import okhttp3.MultipartBody
import okhttp3.ResponseBody

internal class LedgerStubApiFactory(
    private val service: ApiService,
    private val beforeSwitchDispatch: (suspend () -> Unit)? = null,
) : ApiServiceFactory {
    val tokenProviders: MutableList<() -> String?> = mutableListOf()
    val tokenSnapshots: MutableList<String?> = mutableListOf()
    val dispatchedSwitchTokenSnapshots: MutableList<String?> = mutableListOf()
    val baseUrls: MutableList<String> = mutableListOf()

    override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService {
        tokenProviders += tokenProvider
        tokenSnapshots += tokenProvider()
        baseUrls += baseUrl
        val dispatchHook = beforeSwitchDispatch ?: return service
        return object : ApiService by service {
            override suspend fun switchLedger(ledgerId: String): LedgerSwitchResponseDto {
                dispatchHook()
                dispatchedSwitchTokenSnapshots += tokenProvider()
                return service.switchLedger(ledgerId)
            }
        }
    }
}

internal data class LedgerStubApiState(
    var listLedgersResult: LedgerListResponseDto? = null,
    var listLedgersError: Throwable? = null,
    var createResult: LedgerDto? = null,
    var switchResult: LedgerSwitchResponseDto? = null,
    var switchHandler: (suspend (String) -> LedgerSwitchResponseDto)? = null,
    var switchError: Throwable? = null,
    var membersResult: LedgerMemberListResponseDto? = null,
    var auditResult: LedgerAuditListResponseDto? = null,
    var roleUpdateResult: LedgerMemberDto? = null,
    var disableResult: LedgerMemberDto? = null,
    var transferResult: OwnerTransferResponseDto? = null,
    var previewResult: InvitationPreviewResponseDto? = null,
    var previewHandler: (suspend (InvitationPreviewRequestDto) -> InvitationPreviewResponseDto)? = null,
    var previewError: Throwable? = null,
    var acceptResult: InvitationAcceptResponseDto? = null,
    var acceptHandler: (suspend (InvitationAcceptRequestDto) -> InvitationAcceptResponseDto)? = null,
    var acceptError: Throwable? = null,
    var createInvitationResult: com.ticketbox.data.remote.dto.InvitationCreateResponseDto? = null,
    var createInvitationError: Throwable? = null,
)

// Keep only configured ledger behavior here; every other API call fails immediately.
private val unsupportedLedgerApi = java.lang.reflect.Proxy.newProxyInstance(
    ApiService::class.java.classLoader,
    arrayOf(ApiService::class.java),
) { _, _, _ -> error("Unexpected API call") } as ApiService

internal class StubApi(
    private val state: LedgerStubApiState = LedgerStubApiState(),
) : ApiService by unsupportedLedgerApi {
    override suspend fun portableExportLedgers(): LedgerListResponseDto = error("Portable export not configured")
    override fun portableExport(ledgerId: String, download: com.ticketbox.data.remote.PortableDownloadRequest): retrofit2.Call<ResponseBody> =
        error("Portable export not configured")
    override suspend fun originalHealth(id: Long): com.ticketbox.data.remote.dto.OriginalHealthDto = error("Original health not configured")
    override suspend fun verifyOriginal(id: Long, body: com.ticketbox.data.remote.dto.OriginalVerificationRequestDto, idempotencyKey: String): com.ticketbox.data.remote.dto.OriginalCommandReceiptDto = error("Original verification not configured")
    override suspend fun replenishOriginal(id: Long, file: okhttp3.MultipartBody.Part, expectedRowVersion: Long, expectedSha256: String, idempotencyKey: String): com.ticketbox.data.remote.dto.OriginalCommandReceiptDto = error("Original replenishment not configured")
    override suspend fun retryOriginalCleanup(id: Long, body: com.ticketbox.data.remote.dto.OriginalCleanupRequestDto, idempotencyKey: String): com.ticketbox.data.remote.dto.OriginalCommandReceiptDto = error("Original cleanup not configured")
    override suspend fun cancelOriginalCleanup(id: Long, body: com.ticketbox.data.remote.dto.OriginalCleanupRequestDto, idempotencyKey: String): com.ticketbox.data.remote.dto.OriginalCommandReceiptDto = error("Original cleanup not configured")

    override suspend fun ledgerCalendar(ledgerId: String, revision: Long?): com.ticketbox.data.remote.dto.LedgerCalendarDto =
        error("Unexpected ledger calendar query")

    var onLedgerMembers: (() -> Unit)? = null
    var onListLedgers: (() -> Unit)? = null
    var onAcceptInvitation: (() -> Unit)? = null
    var auditError: Throwable? = null
    var listLedgersError: Throwable?
        get() = state.listLedgersError
        set(value) {
            state.listLedgersError = value
        }
    var listLedgersResult: LedgerListResponseDto?
        get() = state.listLedgersResult
        set(value) {
            state.listLedgersResult = value
        }
    val createInvitationTargets: MutableList<String> = mutableListOf()
    val createInvitationRequests: MutableList<com.ticketbox.data.remote.dto.InvitationCreateRequestDto> = mutableListOf()
    val switchRequests: MutableList<String> = mutableListOf()
    val memberLedgerRequests: MutableList<String> = mutableListOf()
    val auditRequests: MutableList<Pair<String, Int>> = mutableListOf()
    val roleUpdateTargets: MutableList<Pair<String, Long>> = mutableListOf()
    val roleUpdateRequests: MutableList<LedgerMemberRoleUpdateRequestDto> = mutableListOf()
    val disableTargets: MutableList<Pair<String, Long>> = mutableListOf()
    val transferTargets: MutableList<Pair<String, Long>> = mutableListOf()
    val previewRequests: MutableList<InvitationPreviewRequestDto> = mutableListOf()
    val acceptRequests: MutableList<InvitationAcceptRequestDto> = mutableListOf()

    // issue #65 slice 6b device routes (body-level so the baselined ctor stays put).
    var devicesResult: com.ticketbox.data.remote.dto.MyDeviceListResponseDto? = null
    var devicesError: Throwable? = null
    var renameDeviceResult: com.ticketbox.data.remote.dto.MyDeviceDto? = null
    var revokeDeviceResult: com.ticketbox.data.remote.dto.MyDeviceDto? = null
    var pairingCodeResult: com.ticketbox.data.remote.dto.PairingCodeResponseDto? = null
    var pairingCodeError: Throwable? = null
    val deviceListRequests: MutableList<String> = mutableListOf()
    val renameDeviceTargets: MutableList<Pair<String, String>> = mutableListOf()
    val renameDeviceRequests: MutableList<com.ticketbox.data.remote.dto.DeviceRenameRequestDto> = mutableListOf()
    val revokeDeviceTargets: MutableList<Pair<String, String>> = mutableListOf()
    var deleteDeviceError: Throwable? = null
    val deleteDeviceTargets: MutableList<Pair<String, String>> = mutableListOf()
    val pairingCodeTargets: MutableList<String> = mutableListOf()
    val pairingCodeRequests: MutableList<com.ticketbox.data.remote.dto.PairingCodeCreateRequestDto> =
        mutableListOf()
    var recycleBinResult: com.ticketbox.data.remote.dto.RecycleBinListResponseDto? = null
    var recycleBinError: Throwable? = null
    var recycleBinRestoreResult: com.ticketbox.data.remote.dto.RecycleBinRestoreResponseDto? = null
    var recycleBinRestoreError: Throwable? = null
    val recycleBinRefreshCount = mutableListOf<Unit>()
    val recycleBinRestoreRequests: MutableList<com.ticketbox.data.remote.dto.RecycleBinRestoreRequestDto> = mutableListOf()

    override suspend fun recurringOccurrence(
        publicId: String,
        month: String,
    ): com.ticketbox.data.remote.dto.RecurringOccurrenceDto = error("Unexpected recurring occurrence read")

    override suspend fun setRecurringOccurrencePayment(
        publicId: String,
        month: String,
        request: com.ticketbox.data.remote.dto.RecurringOccurrencePaymentRequestDto,
        idempotencyKey: String,
    ): com.ticketbox.data.remote.dto.RecurringOccurrenceDto = error("Unexpected recurring occurrence write")

    override suspend fun createRecurringItem(
        request: com.ticketbox.data.remote.dto.RecurringItemCreateRequestDto,
        idempotencyKey: String,
    ): com.ticketbox.data.remote.dto.RecurringItemDto = error("Unexpected createRecurringItem call")

    override suspend fun updateRecurringItem(
        publicId: String,
        request: com.ticketbox.data.remote.dto.RecurringItemUpdateRequestDto,
        idempotencyKey: String,
    ): com.ticketbox.data.remote.dto.RecurringItemDto = error("Unexpected updateRecurringItem call")

    override suspend fun restoreRecurringItem(
        publicId: String,
        request: com.ticketbox.data.remote.dto.RecurringItemTokenRequest,
    ): com.ticketbox.data.remote.dto.RecurringItemDto = error("Unexpected restoreRecurringItem call")

    override suspend fun listLedgers(): LedgerListResponseDto {
        state.listLedgersError?.let { throw it }
        onListLedgers?.invoke()
        return state.listLedgersResult ?: LedgerListResponseDto(ledgers = emptyList())
    }

    override suspend fun createLedger(request: LedgerCreateRequestDto): LedgerDto {
        return state.createResult ?: LedgerDto(
            ledgerId = "L_new",
            name = request.name,
            role = "owner",
            isDefault = false,
            createdAt = "2026-01-01T00:00:00Z",
            archivedAt = null,
        )
    }

    override suspend fun switchLedger(ledgerId: String): LedgerSwitchResponseDto {
        switchRequests += ledgerId
        state.switchError?.let { throw it }
        state.switchHandler?.let { return it(ledgerId) }
        return state.switchResult ?: error("Unexpected switch call")
    }

    override suspend fun ledgerMembers(ledgerId: String): LedgerMemberListResponseDto {
        memberLedgerRequests += ledgerId
        onLedgerMembers?.invoke()
        return state.membersResult ?: error("Unexpected members call")
    }

    override suspend fun ledgerAudit(ledgerId: String, limit: Int): LedgerAuditListResponseDto {
        auditRequests += ledgerId to limit
        auditError?.let { throw it }
        return state.auditResult ?: error("Unexpected audit call")
    }

    override suspend fun updateLedgerMemberRole(
        ledgerId: String,
        memberId: Long,
        request: LedgerMemberRoleUpdateRequestDto,
    ): LedgerMemberDto {
        roleUpdateTargets += ledgerId to memberId
        roleUpdateRequests += request
        return state.roleUpdateResult ?: error("Unexpected role update call")
    }

    override suspend fun disableLedgerMember(ledgerId: String, memberId: Long): LedgerMemberDto {
        disableTargets += ledgerId to memberId
        return state.disableResult ?: error("Unexpected disable call")
    }

    override suspend fun transferLedgerOwner(
        ledgerId: String,
        memberId: Long,
    ): OwnerTransferResponseDto {
        transferTargets += ledgerId to memberId
        return state.transferResult ?: error("Unexpected transfer call")
    }

    override suspend fun createInvitation(
        ledgerId: String,
        request: com.ticketbox.data.remote.dto.InvitationCreateRequestDto,
    ): com.ticketbox.data.remote.dto.InvitationCreateResponseDto {
        createInvitationTargets += ledgerId
        createInvitationRequests += request
        state.createInvitationError?.let { throw it }
        return state.createInvitationResult ?: error("Unexpected createInvitation call")
    }

    override suspend fun previewInvitation(
        request: InvitationPreviewRequestDto,
    ): InvitationPreviewResponseDto {
        previewRequests += request
        state.previewHandler?.let { return it(request) }
        state.previewError?.let { throw it }
        return state.previewResult ?: error("Unexpected preview call")
    }

    override suspend fun acceptInvitation(request: InvitationAcceptRequestDto): InvitationAcceptResponseDto {
        acceptRequests += request
        state.acceptHandler?.let { return it(request) }
        state.acceptError?.let { throw it }
        onAcceptInvitation?.invoke()
        val response = state.acceptResult ?: error("Unexpected accept call")
        return if (response.enrollmentAttemptId == null && request.enrollmentAttemptId != null) {
            response.copy(enrollmentAttemptId = request.enrollmentAttemptId)
        } else {
            response
        }
    }

    override suspend fun goalHistory(publicId: String, limit: Int, beforeVersion: Long?):
        com.ticketbox.data.remote.dto.GoalHistoryResponseDto = error("Unexpected goal definition history")

    override suspend fun recurringHistory(publicId: String, limit: Int, beforeVersion: Long?):
        com.ticketbox.data.remote.dto.RecurringHistoryPageDto = error("Unexpected recurring definition history")

    // issue #65 slice 6b: device routes (records call + returns configured result).
    override suspend fun ledgerDevices(
        ledgerId: String,
    ): com.ticketbox.data.remote.dto.MyDeviceListResponseDto {
        deviceListRequests += ledgerId
        devicesError?.let { throw it }
        return devicesResult ?: error("Unexpected devices call")
    }

    override suspend fun renameLedgerDevice(
        ledgerId: String,
        publicId: String,
        request: com.ticketbox.data.remote.dto.DeviceRenameRequestDto,
    ): com.ticketbox.data.remote.dto.MyDeviceDto {
        renameDeviceTargets += ledgerId to publicId
        renameDeviceRequests += request
        return renameDeviceResult ?: error("Unexpected rename device call")
    }

    override suspend fun revokeLedgerDevice(
        ledgerId: String,
        publicId: String,
    ): com.ticketbox.data.remote.dto.MyDeviceDto {
        revokeDeviceTargets += ledgerId to publicId
        return revokeDeviceResult ?: error("Unexpected revoke device call")
    }

    override suspend fun deleteLedgerDevice(ledgerId: String, publicId: String) {
        deleteDeviceTargets += ledgerId to publicId
        deleteDeviceError?.let { throw it }
    }

    override suspend fun createLedgerDevicePairingCode(
        ledgerId: String,
        request: com.ticketbox.data.remote.dto.PairingCodeCreateRequestDto,
    ): com.ticketbox.data.remote.dto.PairingCodeResponseDto {
        pairingCodeTargets += ledgerId
        pairingCodeRequests += request
        pairingCodeError?.let { throw it }
        return pairingCodeResult ?: error("Unexpected pairing code call")
    }

    override suspend fun recycleBin(): com.ticketbox.data.remote.dto.RecycleBinListResponseDto {
        recycleBinRefreshCount += Unit
        recycleBinError?.let { throw it }
        return recycleBinResult ?: error("Unexpected recycle bin call")
    }

    override suspend fun restoreRecycleBinItem(
        request: com.ticketbox.data.remote.dto.RecycleBinRestoreRequestDto,
    ): com.ticketbox.data.remote.dto.RecycleBinRestoreResponseDto {
        recycleBinRestoreRequests += request
        recycleBinRestoreError?.let { throw it }
        return recycleBinRestoreResult ?: error("Unexpected recycle bin restore call")
    }
}

internal class LedgerFakeSettingsStore : TicketboxSettingsStore {
    override val backgroundSettingsFlow: Flow<BackgroundSettings> = MutableStateFlow(BackgroundSettings())
    private var serverUrl: String? = null
    private var ledgerName: String? = null
    private var ledgersJson: String? = null
    private val ledgerIdFlow = MutableStateFlow<String?>(null)
    var capturedAccountName: String? = null
    var capturedDeviceName: String? = null
    var capturedRole: String? = null
    var capturedBoundAt: String? = null
    fun serverUrl(): String? = serverUrl
    override fun appThemeModeKey(): String? = null
    override fun lastConfirmedSyncAt(): String? = null
    fun accountName(): String? = capturedAccountName
    fun ledgerName(): String? = ledgerName
    fun activeLedgerId(): String? = ledgerIdFlow.value
    fun activeLedgerName(): String? = ledgerName
    override fun availableLedgersJson(): String? = ledgersJson
    fun observeActiveLedgerId(): Flow<String?> = ledgerIdFlow
    fun saveActiveLedger(ledgerId: String, ledgerName: String) {
        ledgerIdFlow.value = ledgerId
        this.ledgerName = ledgerName
    }
    override fun saveAvailableLedgersJson(json: String?) { ledgersJson = json }
    fun deviceName(): String? = capturedDeviceName
    fun role(): String? = capturedRole
    fun boundAt(): String? = capturedBoundAt
    fun saveIdentity(identity: PersistedLedgerIdentity) {
        ledgerIdFlow.value = identity.ledgerId
        ledgerName = identity.ledgerName
        capturedAccountName = identity.accountName
        capturedDeviceName = identity.deviceName
        capturedRole = identity.role
        capturedBoundAt = identity.boundAt
    }
    override fun saveLastConfirmedSyncAt(value: String) = Unit
    override fun clearLastConfirmedSyncAt() = Unit
    override fun clearLastConfirmedSyncAtForLedger(ledgerId: String) = Unit
    override fun clearLedgerScopedRuntimeState() = Unit
    override fun lastUploadAt(): String? = null
    override fun saveLastUploadAt(value: String) = Unit
    override fun saveAppThemeModeKey(modeKey: String) = Unit
    override fun currencyCodeKey(): String? = null
    override fun saveCurrencyCodeKey(currencyKey: String) = Unit
    override fun observeCurrencyCodeKey(): Flow<String?> = MutableStateFlow(null)
    fun saveServerUrl(serverUrl: String) {
        this.serverUrl = serverUrl.trim().trimEnd('/')
    }
    var unlockedMarked: Boolean = false
    fun isBound(): Boolean = !serverUrl.isNullOrBlank()
    override fun markUnlocked() {
        unlockedMarked = true
    }
    override fun markBackgrounded() = Unit
    override fun requiresUnlock(): Boolean = false
    override fun clear() {
        serverUrl = null; ledgerIdFlow.value = null; ledgerName = null; ledgersJson = null
    }
}

internal typealias LedgerFakeTokenStore = TestSessionFixture

internal fun ledgerSessionFixture(
    ledgerId: String,
    ledgerName: String,
    role: String = "owner",
    token: String = "session-token",
    serverUrl: String = "https://api.example.com",
): LedgerFakeTokenStore = LedgerFakeTokenStore(
    serverUrl = serverUrl,
    identity = LocalSessionIdentity(
        accountPublicId = TEST_ACCOUNT_PUBLIC_ID,
        devicePublicId = TEST_DEVICE_PUBLIC_ID,
        accountName = "我",
        ledgerId = ledgerId,
        ledgerName = ledgerName,
        deviceName = "Pixel",
        role = role,
        boundAt = "2026-05-01T00:00:00Z",
    ),
).apply { saveToken(token) }

internal fun existingOwnerSessionFixture(
    ledgerId: String,
    ledgerName: String,
    accountName: String,
    deviceName: String,
    token: String = "session-token",
): LedgerFakeTokenStore = LedgerFakeTokenStore(
    identity = LocalSessionIdentity(
        accountPublicId = TEST_ACCOUNT_PUBLIC_ID,
        devicePublicId = TEST_DEVICE_PUBLIC_ID,
        accountName = accountName,
        ledgerId = ledgerId,
        ledgerName = ledgerName,
        deviceName = deviceName,
        role = "owner",
        boundAt = "2026-05-01T00:00:00Z",
    ),
).apply { saveToken(token) }

internal class LedgerFakeDao : ExpenseDao, com.ticketbox.data.local.ExpenseFactQueryCacheDao by com.ticketbox.data.local.ExpenseFactQueryCacheFake(),
    com.ticketbox.data.local.ExpenseFactInputDao by com.ticketbox.data.local.ExpenseFactInputFake() {
    private val statsCache = com.ticketbox.data.local.StatsProjectionCacheFake()
    override suspend fun clearDebtEntrySnapshots(bindingKey: String, publicId: String) {
        statsCache.byKind(bindingKey, "debt_detail").filter { it.tag == publicId }.forEach(statsCache::delete)
        statsCache.byKind(bindingKey, "debt_activity").filter { it.tag.startsWith("$publicId:") }.forEach(statsCache::delete)
    }
    override suspend fun debtAgreementSnapshots(bindingKey: String) = statsCache.byKind(bindingKey, "debt_agreement")
    override suspend fun debtDirectBarriers(bindingKey: String) = statsCache.byKind(bindingKey, "debt_direct_barrier")
    override suspend fun clearDebtDirectBarriers(bindingKey: String, tokens: List<String>) {
        statsCache.byKind(bindingKey, "debt_direct_barrier").filter { it.tag in tokens }.forEach(statsCache::delete)
    }
    override suspend fun debtReadEpoch(bindingKey: String) = statsCache.find(bindingKey, "debt_read_epoch", "", "", "UTC").singleOrNull()?.responseJson
    override suspend fun clearDebtListSnapshots(bindingKey: String) = statsCache.clearKinds(bindingKey, setOf("debt_list"))
    override suspend fun clearDebtSnapshots(bindingKey: String) = statsCache.clearKinds(bindingKey, setOf("debt_list", "debt_detail", "debt_activity", "debt_agreement"))
    override suspend fun debtResourceDenials(bindingKey: String) = statsCache.byKind(bindingKey, "debt_resource_denial")
    override suspend fun clearDebtResourceDenial(bindingKey: String, publicId: String) {
        statsCache.byKind(bindingKey, "debt_resource_denial").filter { it.tag == publicId }.forEach(statsCache::delete)
    }
    private val goalCache = com.ticketbox.data.local.GoalQueryCacheFake()
    override suspend fun recurringReadEpoch(bindingKey: String) =
        statsCache.find(bindingKey, "recurring_read_epoch", "", "", "UTC").singleOrNull()?.responseJson
    override suspend fun clearRecurringSnapshots(bindingKey: String) = statsCache.clearRecurring(bindingKey)
    override suspend fun saveGoalSnapshots(snapshots: List<com.ticketbox.data.local.GoalQueryCacheEntity>) = goalCache.save(snapshots)
    override suspend fun goalSnapshot(bindingKey: String, timezone: String, queryKey: String) = goalCache.find(bindingKey, timezone, queryKey)
    private val monthlyCache = FakeMonthlyArrangementCacheDao()
    override suspend fun clearMonthlyReadSnapshots() = monthlyCache.clearReadSnapshots()
    override suspend fun clearMonthlyReadSnapshotsForBinding(bindingKey: String) = monthlyCache.clearReadSnapshots(bindingKey)
    override suspend fun monthlyReadSnapshotBindings() = monthlyCache.readSnapshotBindings()
    override suspend fun clearGoalSnapshots() = goalCache.clear(null)
    override suspend fun clearGoalSnapshotsForLedger(ledgerId: String) = goalCache.clear(ledgerId)
    override suspend fun clearGoalSnapshotsForBinding(bindingKey: String) = goalCache.clearBinding(bindingKey)
    override suspend fun clearStatsProjectionsForBinding(bindingKey: String) = statsCache.clearBinding(bindingKey)
    override suspend fun budgetSnapshotsForMonth(bindingKey: String, month: String) = statsCache.budgetMonth(bindingKey, month)
    override suspend fun deleteStatsProjection(snapshot: com.ticketbox.data.local.StatsProjectionCacheEntity) = statsCache.delete(snapshot)
    override suspend fun saveStatsProjection(snapshot: com.ticketbox.data.local.StatsProjectionCacheEntity) = statsCache.save(snapshot)
    override suspend fun statsProjections(bindingKey: String, kind: String, month: String, tag: String,
        timezone: String) = statsCache.find(bindingKey, kind, month, tag, timezone)
    override suspend fun clearStatsProjections() = statsCache.clear(null)
    override suspend fun clearStatsProjectionsForLedger(ledgerId: String) = statsCache.clear(ledgerId)

    private val map = linkedMapOf<Long, ExpenseEntity>()
    private val flows = mutableMapOf<String, MutableStateFlow<List<ExpenseEntity>>>()
    fun insertEntity(entity: ExpenseEntity) { map[entity.id] = entity }
    fun find(id: Long): ExpenseEntity? = map[id]
    override fun observeConfirmed(ledgerId: String): Flow<List<ExpenseEntity>> = flowFor(ledgerId)
    override fun observeConfirmedStreamRoots(ledgerId: String): Flow<List<ExpenseEntity>> =
        MutableStateFlow(emptyList())
    override fun observeConfirmedStreamOffsets(ledgerId: String): Flow<List<ExpenseOffsetStreamEntity>> =
        MutableStateFlow(emptyList())
    override suspend fun getConfirmedStreamOffsets(ledgerId: String): List<ExpenseOffsetStreamEntity> = emptyList()
    override suspend fun confirmedStreamOffsetPublicIdsForLedger(ledgerId: String): List<String> = emptyList()
    override suspend fun getConfirmed(ledgerId: String): List<ExpenseEntity> = map.values.filter { it.ledgerId == ledgerId }
    override suspend fun getPending(ledgerId: String): List<ExpenseEntity> =
        map.values.filter { it.ledgerId == ledgerId && it.status == "pending" }
    override suspend fun findByServerId(ledgerId: String, serverId: Long): ExpenseEntity? =
        map.values.firstOrNull { it.ledgerId == ledgerId && it.serverId == serverId }
    override suspend fun findByServerIds(ledgerId: String, serverIds: List<Long>): List<ExpenseEntity> =
        map.values.filter { it.ledgerId == ledgerId && it.serverId in serverIds.toSet() }
    override suspend fun confirmedServerIdsForLedger(ledgerId: String): List<Long> =
        map.values.filter { it.ledgerId == ledgerId && it.status == "confirmed" && it.serverId != null }
            .mapNotNull { it.serverId }
    override suspend fun localRowIdForClientRef(ledgerId: String, clientRef: String): Long? =
        map.values.firstOrNull { it.ledgerId == ledgerId && it.clientRef == clientRef }?.id
    override suspend fun deleteByLocalId(id: Long) { map.remove(id) }
    override suspend fun insert(expense: ExpenseEntity): Long {
        map[expense.id] = expense
        return expense.id
    }
    override suspend fun insertAll(expenses: List<ExpenseEntity>): List<Long> = expenses.map { insert(it) }
    override suspend fun upsertConfirmedStreamOffsets(offsets: List<ExpenseOffsetStreamEntity>) = Unit
    override suspend fun update(expense: ExpenseEntity) { map[expense.id] = expense }
    override suspend fun updateAll(expenses: List<ExpenseEntity>) { expenses.forEach { update(it) } }
    override suspend fun clear() { map.clear() }
    override suspend fun clearForLedger(ledgerId: String) {
        val ids = map.values.filter { it.ledgerId == ledgerId }.map { it.id }
        ids.forEach { map.remove(it) }
    }
    override suspend fun deleteConfirmedForLedger(ledgerId: String) {
        val ids = map.values.filter { it.ledgerId == ledgerId && it.status == "confirmed" }.map { it.id }
        ids.forEach { map.remove(it) }
    }
    override suspend fun deleteConfirmedByServerIds(ledgerId: String, serverIds: List<Long>) {
        val remove = serverIds.toSet()
        val ids = map.values
            .filter { it.ledgerId == ledgerId && it.status == "confirmed" && it.serverId in remove }
            .map { it.id }
        ids.forEach { map.remove(it) }
    }
    override suspend fun clearConfirmedStreamOffsets() = Unit
    override suspend fun clearConfirmedStreamOffsetsForLedger(ledgerId: String) = Unit
    override suspend fun deleteConfirmedStreamOffsetsByPublicIds(ledgerId: String, publicIds: List<String>) = Unit
    override suspend fun deleteConfirmedStreamOffsetsForRoot(ledgerId: String, rootServerId: Long) = Unit
    private fun flowFor(ledgerId: String): MutableStateFlow<List<ExpenseEntity>> =
        flows.getOrPut(ledgerId) { MutableStateFlow(emptyList()) }
}

internal fun ledgerEntity(id: Long, ledgerId: String, serverId: Long): ExpenseEntity = ExpenseEntity(
    id = id,
    ledgerId = ledgerId,
    serverId = serverId,
    publicId = "p-$id",
    amountCents = 100,
    merchant = "m",
    category = "其他",
    note = null,
    source = "manual",
    thumbnailPath = null,
    imageHash = null,
    rawText = null,
    duplicateStatus = "none",
    duplicateOfId = null,
    duplicateReason = null,
    tags = null,
    valueScore = null,
    regretScore = null,
    status = "confirmed",
    expenseTime = null,
    createdAt = "2026-01-01T00:00:00Z",
    confirmedAt = null,
    updatedAt = null,
    rowVersion = 1L,
)
