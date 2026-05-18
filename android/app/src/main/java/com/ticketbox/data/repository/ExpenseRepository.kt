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

class RepositoryException(message: String) : RuntimeException(message)

interface LedgerActions {
    fun canModifyLedger(): Boolean
    fun lastConfirmedSyncAt(): String?
    fun observeConfirmed(): Flow<List<Expense>>
    suspend fun categories(): Result<List<String>>
    suspend fun tags(): Result<List<String>>
    suspend fun months(): Result<List<String>>
    suspend fun syncConfirmed(
        month: String? = null,
        category: String? = null,
        tag: String? = null,
    ): Result<List<Expense>>
    suspend fun exportConfirmedCsv(
        month: String? = null,
        category: String? = null,
        tag: String? = null,
    ): Result<CsvExport>
    suspend fun createManualExpense(draft: ExpenseDraft): Result<Expense>
}

interface StatsActions {
    fun observeActiveLedgerId(): Flow<String?>
    fun observeConfirmed(): Flow<List<Expense>>
    fun monthlyBudgetCents(): Long?
    fun lastUploadAt(): String?
    suspend fun months(): Result<List<String>>
    suspend fun tags(): Result<List<String>>
    suspend fun monthlyStats(month: String? = null, tag: String? = null): Result<MonthlyStats>
    suspend fun lifestyleStats(month: String? = null): Result<LifestyleStats>
    suspend fun syncConfirmed(
        month: String?,
        category: String?,
        tag: String?,
    ): Result<List<Expense>>
    suspend fun dataQualitySummary(): Result<DataQualitySummary>
}

internal fun backendErrorUserMessage(errorCode: String, serverMessage: String): String {
    return when (errorCode.trim()) {
        "invalid_token" -> "绑定已失效，请重新绑定账本。"
        "legacy_auth_removed" -> "请使用新版绑定方式。"
        "invalid_pairing_code" -> "绑定码无效，请重新输入。"
        "pairing_code_expired" -> "绑定码已过期，请重新获取。"
        "pairing_code_used" -> "绑定码已使用，请重新获取。"
        "file_too_large" -> "上传文件超过大小限制。"
        "unsupported_file_type" -> "不支持的图片格式。"
        "expense_not_found" -> "账单不存在。"
        "amount_required" -> "请先填写金额。"
        "amount_invalid" -> "金额格式不正确。"
        "currency_not_supported" -> "暂不支持这个币种。"
        "exchange_rate_required" -> "请先填写这一天的汇率。"
        "exchange_rate_pending" -> "汇率还没同步完成，稍后再确认。"
        "exchange_rate_invalid" -> "汇率格式不正确。"
        "exchange_rate_base_currency" -> "人民币是基准币种，不需要维护汇率。"
        "image_not_found" -> "图片不存在。"
        "rule_not_found" -> "分类规则不存在。"
        "rule_in_use" -> "分类规则仍在使用，不能删除。"
        "permission_denied" -> "当前角色为只读，无法修改账本。"
        "merchant_alias_not_found" -> "商家别名不存在。"
        "merchant_alias_conflict" -> "商家别名已指向其他商家。"
        "recurring_candidate_not_found" -> "没有找到可确认的固定支出候选。"
        "recurring_item_not_found" -> "固定支出不存在。"
        "recurring_frequency_invalid" -> "固定支出设置不正确。"
        "recurring_status_invalid" -> "固定支出设置不正确。"
        "recurring_item_archived" -> "固定支出已归档，不能继续修改。"
        "notification_source_invalid" -> "通知来源暂不支持。"
        "server_error" -> "暂时处理不了，请稍后再试。"
        "invalid_request" -> "请求参数不正确。"
        "route_not_found" -> "账本版本过旧，请重启电脑上的小票夹后再试。"
        "method_not_allowed" -> "操作方式不正确，请更新 App 后再试。"
        else -> serverMessage.trim().ifBlank { "操作失败。" }
    }
}

class ExpenseRepository(
    private val expenseDao: ExpenseDao,
    private val apiClient: ApiServiceFactory,
    private val settingsStore: TicketboxSettingsStore,
    private val tokenStore: SessionTokenStore,
    private val deviceNameProvider: () -> String = ::defaultAndroidDeviceName,
    private val apiProvider: ApiServiceProvider = ApiServiceProvider(apiClient, settingsStore, tokenStore),
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

    private fun currentTimezoneId(): String {
        return TimeZone.getDefault().id
    }

    fun currentLedgerRole(): String? = settingsStore.role()

    override fun canModifyLedger(): Boolean = ledgerRoleCanModify(settingsStore.role())

    override fun observeActiveLedgerId(): Flow<String?> = settingsStore.observeActiveLedgerId()

    override fun currentActiveLedgerId(): String? = settingsStore.activeLedgerId()

    private fun api(serverUrlOverride: String? = null, tokenOverride: String? = null): ApiService {
        if (serverUrlOverride != null || tokenOverride != null) {
            return apiProvider.temporary(
                requireNotNull(serverUrlOverride ?: settingsStore.serverUrl()) { "账本地址未绑定" },
                tokenOverride,
            )
        }

        return apiProvider.current()
    }

    private data class BoundLedgerApi(
        val service: ApiService,
        val ledgerId: String,
    )

    private fun boundLedgerApi(): BoundLedgerApi {
        val ledgerId = activeLedgerIdOrLegacy()
        val serverUrl = requireNotNull(settingsStore.serverUrl()) { "账本地址未绑定" }
        val token = requireNotNull(tokenStore.getToken()?.takeIf { it.isNotBlank() }) { "账本未绑定" }
        return BoundLedgerApi(
            service = apiProvider.temporary(serverUrl, token),
            ledgerId = ledgerId,
        )
    }

    private fun requireLedgerStillActive(ledgerIdAtRequest: String) {
        if (activeLedgerIdOrLegacy() != ledgerIdAtRequest) {
            throw RepositoryException("账本已切换，请重新操作。")
        }
    }

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

    private fun persistAuthCheck(
        check: com.ticketbox.data.remote.dto.AuthCheckDto,
        expectedLedgerId: String?,
        expectedToken: String?,
    ) {
        if (expectedToken != null && tokenStore.getToken() != expectedToken) return
        val currentLedgerId = settingsStore.activeLedgerId()?.takeIf { it.isNotBlank() }
        if (expectedLedgerId != null && currentLedgerId != expectedLedgerId) return
        settingsStore.saveIdentity(
            accountName = check.accountName,
            ledgerId = check.ledgerId,
            ledgerName = check.ledgerName,
            deviceName = check.deviceName,
            role = check.role,
            boundAt = settingsStore.boundAt() ?: Instant.now().toString(),
        )
    }

    private fun persistServerSettings(settings: ServerSettingsDto, expectedLedgerId: String?) {
        val expected = expectedLedgerId ?: return
        val ledgerId = settingsStore.activeLedgerId()?.takeIf { it.isNotBlank() } ?: return
        if (ledgerId != expected) return
        if (settings.ledgerId != null && settings.ledgerId != expected) return
        settingsStore.saveIdentity(
            accountName = settings.accountName,
            ledgerId = ledgerId,
            ledgerName = settings.ledgerName,
            deviceName = settings.deviceName,
            role = settings.role,
            boundAt = settingsStore.boundAt() ?: Instant.now().toString(),
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
            settingsStore.saveServerUrl(normalized)
            tokenStore.saveToken(pairResponse.sessionToken)
            settingsStore.saveIdentity(
                accountName = pairResponse.accountName,
                ledgerId = pairResponse.ledgerId,
                ledgerName = pairResponse.ledgerName,
                deviceName = pairResponse.deviceName,
                role = pairResponse.role,
                boundAt = Instant.now().toString(),
            )
            settingsStore.markUnlocked()
            expenseDao.clearForLedger(pairResponse.ledgerId)
            settingsStore.clearLastConfirmedSyncAt()
            val restoreFailed = try {
                syncConfirmedFromService(
                    service = api(normalized, pairResponse.sessionToken),
                    replaceCache = true,
                    recordSyncTimestamp = false,
                )
                settingsStore.saveLastConfirmedSyncAt(Instant.now().toString())
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
        val expectedToken = tokenStore.getToken()
        persistAuthCheck(
            check = api().checkAuth(),
            expectedLedgerId = expectedLedgerId,
            expectedToken = expectedToken,
        )
    }

    suspend fun runConnectionDiagnostics(): Result<ConnectionDiagnostics> = errorHandler.safeCall {
        val service = api()
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
        api().pendingExpenses().map { it.toDomain() }
    }

    suspend fun fetchExpense(id: Long): Result<Expense> = errorHandler.safeCall {
        val bound = boundLedgerApi()
        cacheIfConfirmed(bound.service.expense(id), bound.ledgerId).toDomain()
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
        val bound = boundLedgerApi()
        if (expectedLedgerId != null && expectedLedgerId != bound.ledgerId) {
            throw RepositoryException("账本已切换，请重新选择截图上传。")
        }
        val cleanName = fileName
            .trim()
            .ifBlank { "ticketbox-screenshot.jpg" }
            .replace(Regex("[\\\\/:*?\"<>|]"), "_")
        val mediaType = (contentType?.takeIf { it.isNotBlank() } ?: "image/jpeg").toMediaTypeOrNull()
        val body = bytes.toRequestBody(mediaType)
        val filePart = MultipartBody.Part.createFormData("file", cleanName, body)
        var uploadResponse: UploadResponseDto? = null
        val networkDurationMs = measureTimeMillis {
            requireLedgerStillActive(bound.ledgerId)
            uploadResponse = bound.service.uploadScreenshot(filePart, timezone = currentTimezoneId())
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
        if (activeLedgerIdOrLegacy() == bound.ledgerId) {
            settingsStore.saveLastUploadAt(Instant.now().toString())
        }
        response.id
    }

    override suspend fun updateExpense(
        id: Long,
        draft: ExpenseDraft,
        baseline: Expense?,
    ): Result<Expense> = errorHandler.safeCall {
        val bound = boundLedgerApi()
        val updated = cacheIfConfirmed(bound.service.updateExpense(id, draft.toRequest(baseline = baseline)), bound.ledgerId)
        requireLedgerStillActive(bound.ledgerId)
        updated.toDomain()
    }

    suspend fun fetchExpenseItems(id: Long): Result<ExpenseItems> = errorHandler.safeCall {
        api().expenseItems(id).toDomain()
    }

    suspend fun replaceExpenseItems(id: Long, items: List<ExpenseItemDraft>): Result<ExpenseItems> = errorHandler.safeCall {
        if (!canModifyLedger()) {
            throw RepositoryException("当前角色为只读，无法修改账本。")
        }
        val bound = boundLedgerApi()
        val updated = bound.service.replaceExpenseItems(
            id,
            ExpenseItemReplaceRequestDto(items = items.map { it.toRequest() }),
        )
        requireLedgerStillActive(bound.ledgerId)
        updated.toDomain()
    }

    suspend fun fetchExpenseSplits(id: Long): Result<ExpenseSplits> = errorHandler.safeCall {
        api().expenseSplits(id).toDomain()
    }

    suspend fun replaceExpenseSplits(id: Long, splits: List<ExpenseSplitDraft>): Result<ExpenseSplits> = errorHandler.safeCall {
        if (!canModifyLedger()) {
            throw RepositoryException("当前角色为只读，无法修改账本。")
        }
        val bound = boundLedgerApi()
        val updated = bound.service.replaceExpenseSplits(
            id,
            ExpenseSplitReplaceRequestDto(splits = splits.map { it.toRequest() }),
        )
        requireLedgerStillActive(bound.ledgerId)
        updated.toDomain()
    }

    override suspend fun createManualExpense(draft: ExpenseDraft): Result<Expense> = errorHandler.safeCall {
        require(draft.amountCents != null || draft.originalAmountMinor != null) { "请先填写金额。" }
        val bound = boundLedgerApi()
        val created = cacheIfConfirmed(bound.service.createManualExpense(draft.toRequest()), bound.ledgerId)
        requireLedgerStillActive(bound.ledgerId)
        created.toDomain()
    }

    suspend fun createNotificationDraft(draft: NotificationDraft): Result<Expense> = errorHandler.safeCall {
        api().createNotificationDraft(draft.toRequest()).toDomain()
    }

    override suspend fun confirmExpense(id: Long): Result<Expense> = errorHandler.safeCall {
        val bound = boundLedgerApi()
        val confirmed = cacheIfConfirmed(bound.service.confirmExpense(id), bound.ledgerId)
        requireLedgerStillActive(bound.ledgerId)
        confirmed.toDomain()
    }

    private suspend fun cacheIfConfirmed(dto: ExpenseDto, ledgerIdAtRequest: String): ExpenseDto {
        if (dto.status == "confirmed" && activeLedgerIdOrLegacy() == ledgerIdAtRequest) {
            expenseDao.upsertByServerIdForLedger(ledgerIdAtRequest, dto.toEntity(ledgerIdAtRequest))
        }
        return dto
    }

    override suspend fun rejectExpense(id: Long): Result<Expense> = errorHandler.safeCall {
        val bound = boundLedgerApi()
        val rejected = bound.service.rejectExpense(id)
        requireLedgerStillActive(bound.ledgerId)
        rejected.toDomain()
    }

    suspend fun retryOcr(id: Long): Result<Expense> = errorHandler.safeCall {
        val bound = boundLedgerApi()
        val retried = bound.service.retryOcr(id)
        requireLedgerStillActive(bound.ledgerId)
        retried.toDomain()
    }

    override suspend fun markNotDuplicate(id: Long): Result<Expense> = errorHandler.safeCall {
        val bound = boundLedgerApi()
        val updated = bound.service.markNotDuplicate(id)
        requireLedgerStillActive(bound.ledgerId)
        updated.toDomain()
    }

    suspend fun fetchDuplicates(): Result<List<Expense>> = errorHandler.safeCall {
        api().duplicates().map { it.toDomain() }
    }

    override suspend fun fetchThumbnail(id: Long): Result<ProtectedImage> = errorHandler.safeCall {
        val bound = boundLedgerApi()
        val image = readProtectedImage(bound.service.expenseThumbnail(id))
        requireLedgerStillActive(bound.ledgerId)
        image
    }

    suspend fun fetchImage(id: Long): Result<ProtectedImage> = errorHandler.safeCall {
        val bound = boundLedgerApi()
        val image = readProtectedImage(bound.service.expenseImage(id))
        requireLedgerStillActive(bound.ledgerId)
        image
    }

    private suspend fun syncConfirmedFromService(
        service: ApiService,
        month: String? = null,
        category: String? = null,
        tag: String? = null,
        replaceCache: Boolean = false,
        recordSyncTimestamp: Boolean = true,
    ): List<Expense> {
        val ledgerIdAtRequest = activeLedgerIdOrLegacy()
        val collectedDtos = mutableListOf<ExpenseDto>()
        var page = 1
        val pageSize = 50
        var total = Int.MAX_VALUE
        do {
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
            pruneMissing = !replaceCache && month == null && category == null && tag == null,
        )
        if (recordSyncTimestamp) {
            settingsStore.saveLastConfirmedSyncAt(Instant.now().toString())
        }
        return collected
    }

    override suspend fun syncConfirmed(
        month: String?,
        category: String?,
        tag: String?,
    ): Result<List<Expense>> = errorHandler.safeCall {
        syncConfirmedFromService(api(), month, category, tag)
    }

    override suspend fun categories(): Result<List<String>> = errorHandler.safeCall {
        mergeExpenseCategories(api().categories().items)
    }

    override suspend fun tags(): Result<List<String>> = errorHandler.safeCall {
        api().tags().items
    }

    override suspend fun months(): Result<List<String>> = errorHandler.safeCall {
        api().months(timezone = currentTimezoneId()).items
    }

    override suspend fun exportConfirmedCsv(
        month: String?,
        category: String?,
        tag: String?,
    ): Result<CsvExport> = errorHandler.safeCall {
        val cleanMonth = month?.trim()?.ifBlank { null }
        val cleanCategory = category?.trim()?.ifBlank { null }
        val cleanTag = tag?.trim()?.ifBlank { null }
        val response = api().exportCsv(
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

    @OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
    override fun observeConfirmed(): Flow<List<Expense>> =
        // Re-subscribe to the DAO query when the active ledger changes so a
        // token rotation reflects immediately in the UI.
        settingsStore.observeActiveLedgerId()
            .map { it?.takeIf { id -> id.isNotBlank() } ?: "legacy" }
            .distinctUntilChanged()
            .flatMapLatest { id -> expenseDao.observeConfirmed(id).map { rows -> rows.map { it.toDomain() } } }

    override suspend fun monthlyStats(month: String?, tag: String?): Result<MonthlyStats> = errorHandler.safeCall {
        api().monthlyStats(month = month, tag = tag?.trim()?.ifBlank { null }, timezone = currentTimezoneId()).toDomain()
    }

    override suspend fun lifestyleStats(month: String?): Result<LifestyleStats> = errorHandler.safeCall {
        api().lifestyleStats(month = month, timezone = currentTimezoneId()).toDomain()
    }

    suspend fun recurringCandidates(): Result<List<RecurringCandidate>> = errorHandler.safeCall {
        api().recurringCandidates(timezone = currentTimezoneId()).items.map { it.toDomain() }
    }

    override suspend fun dataQualitySummary(): Result<DataQualitySummary> = errorHandler.safeCall {
        api().dataQualitySummary().toDomain()
    }

    suspend fun serverSettings(): Result<ServerSettings> = errorHandler.safeCall {
        val ledgerIdAtRequest = settingsStore.activeLedgerId()?.takeIf { it.isNotBlank() }
        val settings = api().serverSettings()
        persistServerSettings(settings, expectedLedgerId = ledgerIdAtRequest)
        settings.toDomain()
    }

    override fun monthlyBudgetCents(): Long? = settingsStore.monthlyBudgetCents()

    override fun lastConfirmedSyncAt(): String? = settingsStore.lastConfirmedSyncAt()

    override fun lastUploadAt(): String? = settingsStore.lastUploadAt()

    fun saveMonthlyBudgetCents(amountCents: Long?) {
        settingsStore.saveMonthlyBudgetCents(amountCents)
    }

    private fun activeLedgerIdOrLegacy(): String =
        settingsStore.activeLedgerId()?.takeIf { it.isNotBlank() } ?: "legacy"

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

private fun logNetworkWarning(message: String, error: Throwable) {
    runCatching { Log.w("TicketboxNetwork", message, error) }
}

internal fun defaultAndroidDeviceName(): String {
    val manufacturer = android.os.Build.MANUFACTURER.orEmpty().trim()
    val model = android.os.Build.MODEL.orEmpty().trim()
    return listOf(manufacturer, model)
        .filter { it.isNotBlank() }
        .joinToString(" ")
        .ifBlank { "Android 设备" }
}

private fun String.toFileNameSegment(): String {
    return trim()
        .replace(Regex("[\\\\/:*?\"<>|\\s]+"), "_")
        .take(40)
        .ifBlank { "tag" }
}
