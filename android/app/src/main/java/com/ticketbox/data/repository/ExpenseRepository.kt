package com.ticketbox.data.repository

import android.util.Log
import com.ticketbox.BuildConfig
import com.ticketbox.data.local.ExpenseDao
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseItemReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseSplitReplaceRequestDto
import com.ticketbox.data.remote.dto.PairRequestDto
import com.ticketbox.data.remote.dto.ServerSettingsDto
import com.ticketbox.data.remote.dto.UploadResponseDto
import com.ticketbox.domain.model.ConnectionDiagnostics
import com.ticketbox.domain.model.CsvExport
import com.ticketbox.domain.model.DiagnosticCheck
import com.ticketbox.domain.model.DiagnosticStatus
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ExpenseItemDraft
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.ExpenseSplitDraft
import com.ticketbox.domain.model.ExpenseSplits
import com.ticketbox.domain.model.LifestyleStats
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.domain.model.NotificationDraft
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.domain.model.RecurringCandidate
import com.ticketbox.domain.model.DataQualitySummary
import com.ticketbox.domain.model.ServerSettings
import com.ticketbox.domain.model.ledgerRoleCanModify
import com.ticketbox.domain.model.mergeExpenseCategories
import com.ticketbox.security.SessionTokenStore
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.map
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import retrofit2.HttpException
import retrofit2.Response
import java.io.IOException
import java.time.Instant
import java.util.TimeZone
import kotlin.system.measureTimeMillis
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.ResponseBody

class ExpenseRepository(
    private val expenseDao: ExpenseDao,
    private val apiClient: ApiServiceFactory,
    private val settingsStore: TicketboxSettingsStore,
    private val tokenStore: SessionTokenStore,
    private val deviceNameProvider: () -> String = ::defaultAndroidDeviceName,
    private val apiProvider: ApiServiceProvider = ApiServiceProvider(apiClient, settingsStore, tokenStore),
    private val sessionCoordinator: LocalLedgerSessionCoordinator = LocalLedgerSessionCoordinator(
        settingsStore,
        tokenStore,
        expenseDao,
    ),
) : ServerBindingRepository, PendingReviewActions, LedgerActions, GlobalSearchActions, StatsActions {
    private companion object {
        const val NETWORK_LOG_TAG = "TicketboxNetwork"
    }

    private val errorHandler = NetworkErrorHandler(
        settingsStore = settingsStore,
        context = "Repository",
        statusMessages = mapOf(
            404 to "账单不存在。",
            413 to "上传文件超过大小限制。",
        ),
    )
    private val ledgerRequestGuard = LedgerRequestGuard(settingsStore, tokenStore, apiProvider)

    private fun currentTimezoneId(): String {
        return TimeZone.getDefault().id
    }

    fun currentLedgerRole(): String? = settingsStore.role()

    override fun canModifyLedger(): Boolean = ledgerRoleCanModify(settingsStore.role())

    override fun observeActiveLedgerId(): Flow<String?> = settingsStore.observeActiveLedgerId()

    override fun currentActiveLedgerId(): String? = settingsStore.activeLedgerId()

    private fun api(serverUrl: String, token: String): ApiService =
        apiProvider.temporary(serverUrl, token)

    private fun readProtectedImage(response: Response<ResponseBody>): ProtectedImage {
        if (!response.isSuccessful) {
            val errorBody = response.errorBody()?.string()
            if (BuildConfig.DEBUG) {
                Log.w(NETWORK_LOG_TAG, "Protected image request failed: code=${response.code()} body=${errorBody?.take(160)}")
            }
            throw RepositoryException(errorHandler.parseErrorMessage(response.code(), errorBody))
        }
        val body = response.body() ?: throw RepositoryException("图片为空。")
        val contentType = body.contentType()?.toString()
        val bytes = body.use { it.bytes() }
        if (bytes.isEmpty()) {
            throw RepositoryException("图片为空。")
        }
        if (BuildConfig.DEBUG) {
            Log.d(NETWORK_LOG_TAG, "Protected image loaded: contentType=$contentType bytes=${bytes.size}")
        }
        return ProtectedImage(bytes = bytes, contentType = contentType)
    }

    private fun diagnosticErrorMessage(error: Throwable): String {
        return when (error) {
            is HttpException -> errorHandler.parseHttpError(error)
            is IOException -> {
                Log.w(NETWORK_LOG_TAG, networkDiagnosticMessage(error, settingsStore.serverUrl()), error)
                userNetworkMessage(error, settingsStore.serverUrl())
            }
            is RepositoryException -> error.message ?: "操作失败。"
            is IllegalArgumentException -> error.message ?: "请求参数不正确。"
            else -> error.message ?: "操作失败。"
        }
    }

    private suspend fun persistAuthCheck(
        check: com.ticketbox.data.remote.dto.AuthCheckDto,
        expectedSnapshot: LedgerSessionSnapshot,
    ) {
        val expectedLedgerId = expectedSnapshot.activeLedgerId?.takeIf { it.isNotBlank() }
        sessionCoordinator.applyTransitionIfCurrent(
            expectedSnapshot = expectedSnapshot,
            identity = LedgerSessionIdentity(
                accountName = check.accountName,
                ledgerId = check.ledgerId,
                ledgerName = check.ledgerName,
                deviceName = check.deviceName,
                role = check.role,
                boundAt = settingsStore.boundAt() ?: Instant.now().toString(),
            ),
            cacheInvalidation = if (check.ledgerId != expectedLedgerId) {
                LedgerCacheInvalidation.TargetLedger
            } else {
                LedgerCacheInvalidation.None
            },
        )
    }

    private suspend fun persistServerSettings(
        settings: ServerSettingsDto,
        expectedSnapshot: LedgerSessionSnapshot,
        expectedLedgerId: String?,
    ) {
        val expected = expectedLedgerId ?: return
        val ledgerId = expectedSnapshot.activeLedgerId?.takeIf { it.isNotBlank() } ?: return
        if (ledgerId != expected) return
        if (settings.ledgerId != null && settings.ledgerId != expected) return
        sessionCoordinator.applyTransitionIfCurrent(
            expectedSnapshot = expectedSnapshot,
            identity = LedgerSessionIdentity(
                accountName = settings.accountName,
                ledgerId = ledgerId,
                ledgerName = settings.ledgerName,
                deviceName = settings.deviceName,
                role = settings.role,
                boundAt = settingsStore.boundAt() ?: Instant.now().toString(),
            ),
        )
    }

    override suspend fun bindServer(serverUrl: String, pairingCode: String): Result<BindServerResult> {
        return errorHandler.safeCall(serverUrlHint = serverUrl) {
            val normalized = validateBindingInput(serverUrl, pairingCode)
            val pairResponse = apiProvider.unauthenticated(normalized).pairDevice(
                PairRequestDto(
                    pairingCode = pairingCode.trim(),
                    deviceName = deviceNameProvider(),
                    platform = "android",
                ),
            )
            sessionCoordinator.applyTransition(
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
                syncConfirmedFromService(
                    service = api(normalized, pairResponse.sessionToken),
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

    suspend fun testConnection(): Result<Unit> = errorHandler.safeCall {
        val expectedLedgerId = settingsStore.activeLedgerId()?.takeIf { it.isNotBlank() }
        val bound = ledgerRequestGuard.bind(expectedLedgerId = expectedLedgerId)
        val requestSnapshot = sessionCoordinator.currentSnapshot()
        persistAuthCheck(
            check = bound.service.checkAuth(),
            expectedSnapshot = requestSnapshot,
        )
    }

    suspend fun runConnectionDiagnostics(): Result<ConnectionDiagnostics> = errorHandler.safeCall {
        val bound = ledgerRequestGuard.bind()
        val service = bound.service
        val checks = mutableListOf<DiagnosticCheck>()

        suspend fun record(
            name: String,
            successDetail: String,
            block: suspend () -> Unit,
        ) {
            var failure: Throwable? = null
            val elapsedMs = measureTimeMillis {
                try {
                    block()
                } catch (error: Throwable) {
                    failure = error
                }
            }
            val error = failure
            checks += if (error == null) {
                DiagnosticCheck(
                    name = name,
                    status = DiagnosticStatus.Pass,
                    detail = successDetail,
                    elapsedMs = elapsedMs,
                )
            } else {
                DiagnosticCheck(
                    name = name,
                    status = DiagnosticStatus.Fail,
                    detail = diagnosticErrorMessage(error),
                    elapsedMs = elapsedMs,
                )
            }
        }

        var pending = emptyList<Expense>()

        record("身份验证", "访问凭证有效") {
            service.checkAuth()
        }
        record("账本状态", "小票夹服务正常") {
            service.serverSettings()
        }
        record("待确认账单", "可以读取待确认账单") {
            pending = service.pendingExpenses().map { it.toDomain() }
        }
        record("已确认账单", "可以更新账本") {
            service.confirmedExpenses(page = 1, pageSize = 1, timezone = currentTimezoneId())
        }
        record("月度统计", "可以读取月度统计") {
            service.monthlyStats(month = null, timezone = currentTimezoneId())
        }
        record("分类与月份", "可以读取分类和月份") {
            service.categories()
            service.months(timezone = currentTimezoneId())
        }
        record("疑似重复", "可以读取疑似重复账单") {
            service.duplicates()
        }

        val imageCandidate = pending.firstOrNull { it.imagePath != null || it.thumbnailPath != null }
        if (imageCandidate == null) {
            checks += DiagnosticCheck(
                name = "受保护图片",
                status = DiagnosticStatus.Warn,
                detail = "暂无待确认截图，跳过图片检查。",
                elapsedMs = 0,
            )
        } else {
            record("受保护图片", "截图预览可以打开") {
                readProtectedImage(service.expenseThumbnail(imageCandidate.id))
            }
        }

        ConnectionDiagnostics(checks)
    }

    override suspend fun fetchPending(): Result<List<Expense>> = errorHandler.safeCall {
        ledgerRequestGuard.guardedCall { api ->
            api.pendingExpenses().map { it.toDomain() }
        }
    }

    suspend fun fetchExpense(id: Long): Result<Expense> = errorHandler.safeCall {
        val bound = ledgerRequestGuard.bind()
        cacheIfConfirmed(bound.call { it.expense(id) }, bound.ledgerId).toDomain()
    }

    override suspend fun uploadScreenshot(
        fileName: String,
        contentType: String?,
        bytes: ByteArray,
        preparationDurationMs: Long?,
        sourceSizeBytes: Long?,
        expectedLedgerId: String?,
    ): Result<Long> = errorHandler.safeCall {
        require(bytes.isNotEmpty()) { "请选择一张账单截图。" }
        val bound = ledgerRequestGuard.bind(
            expectedLedgerId = expectedLedgerId,
            ledgerChangedMessage = LedgerRequestGuard.UPLOAD_LEDGER_CHANGED_MESSAGE,
        )
        val cleanName = fileName
            .trim()
            .ifBlank { "ticketbox-screenshot.jpg" }
            .replace(Regex("[\\\\/:*?\"<>|]"), "_")
        val mediaType = (contentType?.takeIf { it.isNotBlank() } ?: "image/jpeg").toMediaTypeOrNull()
        val body = bytes.toRequestBody(mediaType)
        val filePart = MultipartBody.Part.createFormData("file", cleanName, body)
        var uploadResponse: UploadResponseDto? = null
        val networkDurationMs = measureTimeMillis {
            uploadResponse = bound.call(
                ledgerChangedMessage = LedgerRequestGuard.UPLOAD_LEDGER_CHANGED_MESSAGE,
            ) { it.uploadScreenshot(filePart, timezone = currentTimezoneId()) }
        }
        val response = requireNotNull(uploadResponse)
        if (BuildConfig.DEBUG) {
            Log.d(
                NETWORK_LOG_TAG,
                buildString {
                    append("Screenshot upload timing: ")
                    append("prepare_ms=").append(preparationDurationMs ?: -1)
                    append(" network_ms=").append(networkDurationMs)
                    append(" server_ms=").append(response.durationMs ?: -1)
                    append(" source_bytes=").append(sourceSizeBytes ?: -1)
                    append(" upload_bytes=").append(response.uploadSizeBytes ?: bytes.size)
                    append(" server_breakdown=").append(response.timingMs.orEmpty())
                },
            )
        }
        if (bound.isStillActive()) {
            settingsStore.saveLastUploadAt(Instant.now().toString())
        }
        response.id
    }

    override suspend fun updateExpense(
        id: Long,
        draft: ExpenseDraft,
        baseline: Expense?,
    ): Result<Expense> = errorHandler.safeCall {
        val bound = ledgerRequestGuard.bind()
        val updated = cacheIfConfirmed(bound.call { it.updateExpense(id, draft.toRequest(baseline = baseline)) }, bound.ledgerId)
        updated.toDomain()
    }

    suspend fun fetchExpenseItems(id: Long): Result<ExpenseItems> = errorHandler.safeCall {
        val bound = ledgerRequestGuard.bind()
        bound.call { it.expenseItems(id) }.toDomain()
    }

    suspend fun replaceExpenseItems(id: Long, items: List<ExpenseItemDraft>): Result<ExpenseItems> = errorHandler.safeCall {
        if (!canModifyLedger()) {
            throw RepositoryException("当前角色为只读，无法修改账本。")
        }
        val bound = ledgerRequestGuard.bind()
        val updated = bound.call {
            it.replaceExpenseItems(
                id,
                ExpenseItemReplaceRequestDto(items = items.map { item -> item.toRequest() }),
            )
        }
        updated.toDomain()
    }

    suspend fun acknowledgeExpenseItemsMismatch(id: Long): Result<ExpenseItems> = errorHandler.safeCall {
        if (!canModifyLedger()) {
            throw RepositoryException("当前角色为只读，无法修改账本。")
        }
        val bound = ledgerRequestGuard.bind()
        bound.call { it.acknowledgeExpenseItemsMismatch(id) }.toDomain()
    }

    // ADR-0029 bill split
    suspend fun createBillSplitInvitation(
        expenseId: Long,
        receiverAccountId: Long,
        amountCents: Long,
    ): Result<com.ticketbox.domain.model.BillSplitSent> = errorHandler.safeCall {
        if (!canModifyLedger()) {
            throw RepositoryException("当前角色为只读，无法修改账本。")
        }
        val bound = ledgerRequestGuard.bind()
        bound.call {
            it.createBillSplitInvitation(
                expenseId,
                com.ticketbox.data.remote.dto.BillSplitInviteRequestDto(receiverAccountId, amountCents),
            )
        }.toDomain()
    }

    suspend fun fetchBillSplitInbox(): Result<List<com.ticketbox.domain.model.BillSplitInbox>> = errorHandler.safeCall {
        val bound = ledgerRequestGuard.bind()
        bound.call { it.listBillSplitInbox() }.items.map { it.toDomain() }
    }

    suspend fun fetchBillSplitSent(): Result<List<com.ticketbox.domain.model.BillSplitSent>> = errorHandler.safeCall {
        val bound = ledgerRequestGuard.bind()
        bound.call { it.listBillSplitSent() }.items.map { it.toDomain() }
    }

    suspend fun acceptBillSplitInvitation(
        publicId: String,
        targetLedgerId: String,
    ): Result<com.ticketbox.domain.model.BillSplitInbox> = errorHandler.safeCall {
        val bound = ledgerRequestGuard.bind()
        bound.call {
            it.acceptBillSplitInvitation(
                publicId,
                com.ticketbox.data.remote.dto.BillSplitAcceptRequestDto(targetLedgerId),
            )
        }.toDomain()
    }

    suspend fun rejectBillSplitInvitation(publicId: String): Result<com.ticketbox.domain.model.BillSplitInbox> = errorHandler.safeCall {
        val bound = ledgerRequestGuard.bind()
        bound.call { it.rejectBillSplitInvitation(publicId) }.toDomain()
    }

    suspend fun cancelBillSplitInvitation(publicId: String): Result<com.ticketbox.domain.model.BillSplitSent> = errorHandler.safeCall {
        if (!canModifyLedger()) {
            throw RepositoryException("当前角色为只读，无法修改账本。")
        }
        val bound = ledgerRequestGuard.bind()
        bound.call { it.cancelBillSplitInvitation(publicId) }.toDomain()
    }

    // ADR-0030 background tasks
    suspend fun fetchBackgroundTasks(): Result<List<com.ticketbox.domain.model.BackgroundTask>> = errorHandler.safeCall {
        val bound = ledgerRequestGuard.bind()
        bound.call { it.listBackgroundTasks() }.items.map { it.toDomain() }
    }

    suspend fun cancelBackgroundTask(publicId: String): Result<com.ticketbox.domain.model.BackgroundTask> = errorHandler.safeCall {
        val bound = ledgerRequestGuard.bind()
        bound.call { it.cancelBackgroundTask(publicId) }.toDomain()
    }

    suspend fun fetchExpenseSplits(id: Long): Result<ExpenseSplits> = errorHandler.safeCall {
        val bound = ledgerRequestGuard.bind()
        bound.call { it.expenseSplits(id) }.toDomain()
    }

    suspend fun replaceExpenseSplits(id: Long, splits: List<ExpenseSplitDraft>): Result<ExpenseSplits> = errorHandler.safeCall {
        if (!canModifyLedger()) {
            throw RepositoryException("当前角色为只读，无法修改账本。")
        }
        val bound = ledgerRequestGuard.bind()
        val updated = bound.call {
            it.replaceExpenseSplits(
                id,
                ExpenseSplitReplaceRequestDto(splits = splits.map { split -> split.toRequest() }),
            )
        }
        updated.toDomain()
    }

    override suspend fun createManualExpense(draft: ExpenseDraft): Result<Expense> = errorHandler.safeCall {
        require(draft.amountCents != null || draft.originalAmountMinor != null) { "请先填写金额。" }
        val bound = ledgerRequestGuard.bind()
        val created = cacheIfConfirmed(bound.call { it.createManualExpense(draft.toRequest()) }, bound.ledgerId)
        created.toDomain()
    }

    suspend fun createNotificationDraft(
        draft: NotificationDraft,
        expectedLedgerId: String? = null,
    ): Result<Expense> = errorHandler.safeCall {
        val bound = ledgerRequestGuard.bind(expectedLedgerId = expectedLedgerId)
        val created = bound.call { it.createNotificationDraft(draft.toRequest()) }
        created.toDomain()
    }

    override suspend fun confirmExpense(id: Long): Result<Expense> = errorHandler.safeCall {
        val bound = ledgerRequestGuard.bind()
        val confirmed = cacheIfConfirmed(bound.call { it.confirmExpense(id) }, bound.ledgerId)
        confirmed.toDomain()
    }

    private suspend fun cacheIfConfirmed(dto: ExpenseDto, ledgerIdAtRequest: String): ExpenseDto {
        if (dto.status == "confirmed" && activeLedgerIdOrLegacy() == ledgerIdAtRequest) {
            expenseDao.upsertByServerIdForLedger(ledgerIdAtRequest, dto.toEntity(ledgerIdAtRequest))
        }
        return dto
    }

    override suspend fun rejectExpense(id: Long): Result<Expense> = errorHandler.safeCall {
        val bound = ledgerRequestGuard.bind()
        val rejected = bound.call { it.rejectExpense(id) }
        rejected.toDomain()
    }

    suspend fun retryOcr(id: Long): Result<Expense> = errorHandler.safeCall {
        val bound = ledgerRequestGuard.bind()
        val retried = bound.call { it.retryOcr(id) }
        retried.toDomain()
    }

    override suspend fun markNotDuplicate(id: Long): Result<Expense> = errorHandler.safeCall {
        val bound = ledgerRequestGuard.bind()
        val updated = cacheIfConfirmed(bound.call { it.markNotDuplicate(id) }, bound.ledgerId)
        updated.toDomain()
    }

    suspend fun fetchDuplicates(): Result<List<Expense>> = errorHandler.safeCall {
        ledgerRequestGuard.guardedCall { api ->
            api.duplicates().map { it.toDomain() }
        }
    }

    override suspend fun fetchThumbnail(id: Long): Result<ProtectedImage> = errorHandler.safeCall {
        val bound = ledgerRequestGuard.bind()
        bound.call { readProtectedImage(it.expenseThumbnail(id)) }
    }

    suspend fun fetchImage(id: Long): Result<ProtectedImage> = errorHandler.safeCall {
        val bound = ledgerRequestGuard.bind()
        bound.call { readProtectedImage(it.expenseImage(id)) }
    }

    private suspend fun syncConfirmedFromService(
        service: ApiService,
        ledgerIdAtRequest: String = activeLedgerIdOrLegacy(),
        month: String? = null,
        category: String? = null,
        tag: String? = null,
        replaceCache: Boolean = false,
        recordSyncTimestamp: Boolean = true,
    ): List<Expense> {
        val isFullLedgerSync = month == null && category == null && tag == null
        val collectedDtos = mutableListOf<ExpenseDto>()
        var page = 1
        val pageSize = 50
        var total = Int.MAX_VALUE
        do {
            if (activeLedgerIdOrLegacy() != ledgerIdAtRequest) {
                return emptyList()
            }
            val response = service.confirmedExpenses(
                page = page,
                pageSize = pageSize,
                month = month,
                category = category,
                tag = tag,
                timezone = currentTimezoneId(),
            )
            total = response.total
            collectedDtos += response.items
            if (response.items.isEmpty() && collectedDtos.size < total) {
                throw RepositoryException("账本同步分页异常，请稍后再试。")
            }
            page += 1
        } while (collectedDtos.size < total)

        val collected = collectedDtos.map { it.toDomain() }
        if (activeLedgerIdOrLegacy() != ledgerIdAtRequest) {
            return emptyList()
        }

        val entities = collectedDtos.map { it.toEntity(ledgerIdAtRequest) }
        expenseDao.applyConfirmedSyncForLedger(
            ledgerId = ledgerIdAtRequest,
            expenses = entities,
            replaceCache = replaceCache,
            pruneMissing = !replaceCache && isFullLedgerSync,
        )
        if (recordSyncTimestamp && isFullLedgerSync) {
            settingsStore.saveLastConfirmedSyncAtForLedger(ledgerIdAtRequest, Instant.now().toString())
        }
        return collected
    }

    override suspend fun syncConfirmed(
        month: String?,
        category: String?,
        tag: String?,
    ): Result<List<Expense>> = errorHandler.safeCall {
        val bound = ledgerRequestGuard.bind()
        syncConfirmedFromService(
            service = bound.service,
            ledgerIdAtRequest = bound.ledgerId,
            month = month,
            category = category,
            tag = tag,
        )
    }

    override suspend fun categories(): Result<List<String>> = errorHandler.safeCall {
        ledgerRequestGuard.guardedCall { api ->
            mergeExpenseCategories(api.categories().items)
        }
    }

    override suspend fun tags(): Result<List<String>> = errorHandler.safeCall {
        ledgerRequestGuard.guardedCall { api ->
            api.tags().items
        }
    }

    override suspend fun months(): Result<List<String>> = errorHandler.safeCall {
        ledgerRequestGuard.guardedCall { api ->
            api.months(timezone = currentTimezoneId()).items
        }
    }

    override suspend fun exportConfirmedCsv(
        month: String?,
        category: String?,
        tag: String?,
    ): Result<CsvExport> = errorHandler.safeCall {
        val cleanMonth = month?.trim()?.ifBlank { null }
        val cleanCategory = category?.trim()?.ifBlank { null }
        val cleanTag = tag?.trim()?.ifBlank { null }
        ledgerRequestGuard.guardedCall { api ->
            val response = api.exportCsv(
                month = cleanMonth,
                category = cleanCategory,
                tag = cleanTag,
                timezone = currentTimezoneId(),
            )
            if (!response.isSuccessful) {
                throw RepositoryException(errorHandler.parseErrorMessage(response.code(), response.errorBody()?.string()))
            }
            val body = response.body() ?: throw RepositoryException("导出内容为空。")
            val fileName = buildString {
                append("ticketbox-expenses")
                if (cleanMonth != null) append("-").append(cleanMonth)
                if (cleanTag != null) append("-tag-").append(cleanTag.toFileNameSegment())
                append(".csv")
            }
            CsvExport(fileName = fileName, bytes = body.use { it.bytes() })
        }
    }

    @OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
    override fun observeConfirmed(): Flow<List<Expense>> =
        // Re-subscribe to the DAO query when the active ledger changes so a
        // token rotation reflects immediately in the UI.
        settingsStore.observeActiveLedgerId()
            .map { it?.takeIf { id -> id.isNotBlank() } ?: "legacy" }
            .distinctUntilChanged()
            .flatMapLatest { id -> expenseDao.observeConfirmed(id).map { rows -> rows.map { it.toDomain() } } }

    override suspend fun monthlyStats(month: String?, tag: String?): Result<MonthlyStats> = errorHandler.safeCall {
        ledgerRequestGuard.guardedCall { api ->
            api.monthlyStats(month = month, tag = tag?.trim()?.ifBlank { null }, timezone = currentTimezoneId()).toDomain()
        }
    }

    override suspend fun lifestyleStats(month: String?): Result<LifestyleStats> = errorHandler.safeCall {
        ledgerRequestGuard.guardedCall { api ->
            api.lifestyleStats(month = month, timezone = currentTimezoneId()).toDomain()
        }
    }

    suspend fun recurringCandidates(): Result<List<RecurringCandidate>> = errorHandler.safeCall {
        ledgerRequestGuard.guardedCall { api ->
            api.recurringCandidates(timezone = currentTimezoneId()).items.map { it.toDomain() }
        }
    }

    override suspend fun dataQualitySummary(): Result<DataQualitySummary> = errorHandler.safeCall {
        ledgerRequestGuard.guardedCall { api ->
            api.dataQualitySummary().toDomain()
        }
    }

    suspend fun serverSettings(): Result<ServerSettings> = errorHandler.safeCall {
        ledgerRequestGuard.guardedCall { api ->
            val requestSnapshot = sessionCoordinator.currentSnapshot()
            val settings = api.serverSettings()
            persistServerSettings(
                settings = settings,
                expectedSnapshot = requestSnapshot,
                expectedLedgerId = ledgerId,
            )
            settings.toDomain()
        }
    }

    override fun monthlyBudgetCents(): Long? = settingsStore.monthlyBudgetCents()

    override fun lastConfirmedSyncAt(): String? = settingsStore.lastConfirmedSyncAt()

    override fun lastUploadAt(): String? = settingsStore.lastUploadAt()

    fun saveMonthlyBudgetCents(amountCents: Long?) {
        settingsStore.saveMonthlyBudgetCents(amountCents)
    }

    private fun activeLedgerIdOrLegacy(): String = ledgerRequestGuard.activeLedgerIdOrLegacy()

    suspend fun clearLocalCache() {
        expenseDao.clear()
        settingsStore.clearLastConfirmedSyncAt()
    }

    override suspend fun clearBinding() {
        apiProvider.clear()
        expenseDao.clear()
        settingsStore.clear()
        tokenStore.clear()
    }
}
