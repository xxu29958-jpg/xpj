package com.ticketbox.data.repository

import com.ticketbox.data.local.ExpenseDao
import com.ticketbox.data.local.ExpenseEntity
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.AuthCheckDto
import com.ticketbox.data.remote.dto.CategoriesDto
import com.ticketbox.data.remote.dto.CategoryRuleDto
import com.ticketbox.data.remote.dto.CategoryRuleRequest
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.data.remote.dto.LifestyleStatsDto
import com.ticketbox.data.remote.dto.MonthlyStatsDto
import com.ticketbox.data.remote.dto.MonthsDto
import com.ticketbox.data.remote.dto.PaginatedExpensesDto
import com.ticketbox.data.remote.dto.PairRequestDto
import com.ticketbox.data.remote.dto.PairResponseDto
import com.ticketbox.data.remote.dto.ServerSettingsDto
import com.ticketbox.data.remote.dto.StatusDto
import com.ticketbox.data.remote.dto.UploadResponseDto
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.security.SessionTokenStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.runTest
import okhttp3.MultipartBody
import okhttp3.ResponseBody
import retrofit2.Response
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class ExpenseRepositoryBindingTest {
    @Test
    fun bindSavesSessionAndIdentityBeforeConfirmedRestoreFailure() = runTest {
        val events = mutableListOf<String>()
        val settingsStore = FakeTicketboxSettingsStore(events)
        val tokenStore = FakeSessionTokenStore(events)
        val apiService = FakeApiService(events, confirmedFailuresRemaining = 1)
        val repository = ExpenseRepository(
            expenseDao = FakeExpenseDao(),
            apiClient = FakeApiServiceFactory(apiService),
            settingsStore = settingsStore,
            tokenStore = tokenStore,
            deviceNameProvider = { "Android Test Device" },
        )

        val result = repository.bindServer("https://api.zen70.cn/", "123456").getOrThrow()

        assertTrue(result.confirmedRestoreFailed)
        assertEquals("https://api.zen70.cn", settingsStore.serverUrl())
        assertEquals("session-token", tokenStore.getToken())
        assertEquals("我", settingsStore.accountName())
        assertEquals("我的小票夹", settingsStore.ledgerName())
        assertEquals("Android Test Device", settingsStore.deviceName())
        assertEquals("owner", settingsStore.role())
        assertTrue(settingsStore.isBound())
        assertTrue(events.indexOf("saveServerUrl") < events.indexOf("syncConfirmed"))
        assertTrue(events.indexOf("saveToken") < events.indexOf("syncConfirmed"))
        assertTrue(events.indexOf("saveIdentity") < events.indexOf("syncConfirmed"))
    }

    @Test
    fun manualConfirmedSyncStillWorksAfterBindRestoreFailure() = runTest {
        val events = mutableListOf<String>()
        val dao = FakeExpenseDao()
        val settingsStore = FakeTicketboxSettingsStore(events)
        val tokenStore = FakeSessionTokenStore(events)
        val apiService = FakeApiService(events, confirmedFailuresRemaining = 1)
        val apiFactory = FakeApiServiceFactory(apiService)
        val repository = ExpenseRepository(
            expenseDao = dao,
            apiClient = apiFactory,
            settingsStore = settingsStore,
            tokenStore = tokenStore,
            deviceNameProvider = { "Android Test Device" },
        )

        val bindResult = repository.bindServer("https://api.zen70.cn", "123456").getOrThrow()
        val syncResult = repository.syncConfirmed().getOrThrow()

        assertTrue(bindResult.confirmedRestoreFailed)
        assertEquals(1, syncResult.size)
        assertEquals("高德", dao.getConfirmed("owner").single().merchant)
        assertEquals("session-token", apiFactory.tokenValues.last())
    }
}

private class FakeApiServiceFactory(
    private val service: FakeApiService,
) : ApiServiceFactory {
    val tokenValues = mutableListOf<String?>()

    override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService {
        tokenValues += tokenProvider()
        return service
    }
}

private class FakeApiService(
    private val events: MutableList<String>,
    private var confirmedFailuresRemaining: Int,
) : ApiService {
    override suspend fun pairDevice(request: PairRequestDto): PairResponseDto {
        return PairResponseDto(
            sessionToken = "session-token",
            accountName = "我",
            ledgerId = "owner",
            ledgerName = "我的小票夹",
            deviceName = request.deviceName,
            role = "owner",
        )
    }

    override suspend fun confirmedExpenses(
        page: Int,
        pageSize: Int,
        month: String?,
        category: String?,
        timezone: String?,
    ): PaginatedExpensesDto {
        events += "syncConfirmed"
        if (confirmedFailuresRemaining > 0) {
            confirmedFailuresRemaining -= 1
            throw IOException("restore unavailable")
        }
        return PaginatedExpensesDto(
            items = listOf(confirmedExpenseDto()),
            page = page,
            pageSize = pageSize,
            total = 1,
        )
    }

    override suspend fun checkAuth(): AuthCheckDto = unsupported()

    override suspend fun pendingExpenses(): List<ExpenseDto> = unsupported()

    override suspend fun categories(): CategoriesDto = unsupported()

    override suspend fun months(timezone: String?): MonthsDto = unsupported()

    override suspend fun exportCsv(month: String?, category: String?, timezone: String?): Response<ResponseBody> = unsupported()

    override suspend fun createManualExpense(request: ExpenseUpdateRequest): ExpenseDto = unsupported()

    override suspend fun uploadScreenshot(file: MultipartBody.Part, timezone: String?): UploadResponseDto = unsupported()

    override suspend fun updateExpense(id: Long, request: ExpenseUpdateRequest): ExpenseDto = unsupported()

    override suspend fun confirmExpense(id: Long): ExpenseDto = unsupported()

    override suspend fun rejectExpense(id: Long): ExpenseDto = unsupported()

    override suspend fun retryOcr(id: Long): ExpenseDto = unsupported()

    override suspend fun markNotDuplicate(id: Long): ExpenseDto = unsupported()

    override suspend fun expenseImage(id: Long): Response<ResponseBody> = unsupported()

    override suspend fun expenseThumbnail(id: Long): Response<ResponseBody> = unsupported()

    override suspend fun duplicates(): List<ExpenseDto> = unsupported()

    override suspend fun categoryRules(): List<CategoryRuleDto> = unsupported()

    override suspend fun createCategoryRule(request: CategoryRuleRequest): CategoryRuleDto = unsupported()

    override suspend fun updateCategoryRule(id: Long, request: CategoryRuleRequest): CategoryRuleDto = unsupported()

    override suspend fun deleteCategoryRule(id: Long): StatusDto = unsupported()

    override suspend fun serverSettings(): ServerSettingsDto = unsupported()

    override suspend fun monthlyStats(month: String?, timezone: String?): MonthlyStatsDto = unsupported()

    override suspend fun lifestyleStats(month: String?, timezone: String?): LifestyleStatsDto = unsupported()
    override suspend fun recurringCandidates(timezone: String?): com.ticketbox.data.remote.dto.RecurringCandidatesResponseDto = unsupported()
    override suspend fun dataQualitySummary(): com.ticketbox.data.remote.dto.DataQualitySummaryDto = unsupported()

    override suspend fun listLedgers(): com.ticketbox.data.remote.dto.LedgerListResponseDto = unsupported()

    override suspend fun createLedger(request: com.ticketbox.data.remote.dto.LedgerCreateRequestDto): com.ticketbox.data.remote.dto.LedgerDto = unsupported()

    override suspend fun switchLedger(ledgerId: String): com.ticketbox.data.remote.dto.LedgerSwitchResponseDto = unsupported()

    private fun confirmedExpenseDto(): ExpenseDto {
        return ExpenseDto(
            id = 9,
            publicId = "691da31d-e8d7-49b0-bece-ec6f61c044b2",
            amountCents = 175479,
            merchant = "高德",
            category = "交通",
            note = "",
            source = "Android截图",
            imagePath = null,
            thumbnailPath = null,
            imageHash = null,
            rawText = null,
            confidence = null,
            duplicateStatus = "none",
            duplicateOfId = null,
            duplicateReason = null,
            tags = null,
            valueScore = null,
            regretScore = null,
            status = "confirmed",
            expenseTime = "2026-05-07T07:29:00Z",
            createdAt = "2026-05-09T08:08:13Z",
            updatedAt = "2026-05-09T08:12:40Z",
            confirmedAt = "2026-05-09T08:12:40Z",
            rejectedAt = null,
        )
    }
}

private class FakeTicketboxSettingsStore(
    private val events: MutableList<String> = mutableListOf(),
) : TicketboxSettingsStore {
    override val backgroundSettingsFlow: Flow<BackgroundSettings> = MutableStateFlow(BackgroundSettings())
    private var serverUrl: String? = null
    private var accountName: String? = null
    private val ledgerIdFlow = MutableStateFlow<String?>(null)
    private var ledgerName: String? = null
    private var availableLedgersJson: String? = null
    private var deviceName: String? = null
    private var role: String? = null
    private var boundAt: String? = null
    private var lastConfirmedSyncAt: String? = null
    private var lastUploadAt: String? = null
    private var monthlyBudgetCents: Long? = null
    private var appSkinKey: String? = null

    override fun serverUrl(): String? = serverUrl

    override fun appSkinKey(): String? = appSkinKey

    override fun monthlyBudgetCents(): Long? = monthlyBudgetCents

    override fun saveMonthlyBudgetCents(amountCents: Long?) {
        monthlyBudgetCents = amountCents
    }

    override fun lastConfirmedSyncAt(): String? = lastConfirmedSyncAt

    override fun accountName(): String? = accountName

    override fun ledgerName(): String? = ledgerName

    override fun activeLedgerId(): String? = ledgerIdFlow.value

    override fun activeLedgerName(): String? = ledgerName

    override fun availableLedgersJson(): String? = availableLedgersJson

    override fun observeActiveLedgerId(): Flow<String?> = ledgerIdFlow

    override fun saveActiveLedger(ledgerId: String, ledgerName: String) {
        events += "saveActiveLedger"
        ledgerIdFlow.value = ledgerId
        this.ledgerName = ledgerName
    }

    override fun saveAvailableLedgersJson(json: String?) {
        availableLedgersJson = json
    }

    override fun deviceName(): String? = deviceName

    override fun role(): String? = role

    override fun boundAt(): String? = boundAt

    override fun saveIdentity(
        accountName: String,
        ledgerId: String,
        ledgerName: String,
        deviceName: String,
        role: String,
        boundAt: String,
    ) {
        events += "saveIdentity"
        this.accountName = accountName
        ledgerIdFlow.value = ledgerId
        this.ledgerName = ledgerName
        this.deviceName = deviceName
        this.role = role
        this.boundAt = boundAt
    }

    override fun saveLastConfirmedSyncAt(value: String) {
        lastConfirmedSyncAt = value
    }

    override fun clearLastConfirmedSyncAt() {
        lastConfirmedSyncAt = null
    }

    override fun lastUploadAt(): String? = lastUploadAt

    override fun saveLastUploadAt(value: String) {
        lastUploadAt = value
    }

    override fun saveAppSkinKey(skinKey: String) {
        appSkinKey = skinKey
    }

    override fun saveServerUrl(serverUrl: String) {
        events += "saveServerUrl"
        this.serverUrl = serverUrl.trim().trimEnd('/')
    }

    override fun isBound(): Boolean = !serverUrl.isNullOrBlank()

    override fun markUnlocked() = Unit

    override fun markBackgrounded() = Unit

    override fun requiresUnlock(): Boolean = false

    override fun clear() {
        serverUrl = null
        accountName = null
        ledgerIdFlow.value = null
        ledgerName = null
        deviceName = null
        role = null
        boundAt = null
        lastConfirmedSyncAt = null
        lastUploadAt = null
    }
}

private class FakeSessionTokenStore(
    private val events: MutableList<String> = mutableListOf(),
) : SessionTokenStore {
    private var token: String? = null

    override fun saveToken(token: String) {
        events += "saveToken"
        this.token = token
    }

    override fun getToken(): String? = token

    override fun clear() {
        token = null
    }
}

private class FakeExpenseDao : ExpenseDao {
    private val expenses = linkedMapOf<Long, ExpenseEntity>()
    private val flows = mutableMapOf<String, MutableStateFlow<List<ExpenseEntity>>>()
    private var nextId = 1L

    override fun observeConfirmed(ledgerId: String): Flow<List<ExpenseEntity>> = flowFor(ledgerId)

    override suspend fun getConfirmed(ledgerId: String): List<ExpenseEntity> {
        return expenses.values
            .filter { it.ledgerId == ledgerId && it.status == "confirmed" }
            .sortedByDescending { it.expenseTime ?: it.confirmedAt ?: it.createdAt }
    }

    override suspend fun findByServerId(ledgerId: String, serverId: Long): ExpenseEntity? {
        return expenses.values.firstOrNull { it.ledgerId == ledgerId && it.serverId == serverId }
    }

    override suspend fun findByServerIds(ledgerId: String, serverIds: List<Long>): List<ExpenseEntity> {
        val wanted = serverIds.toSet()
        return expenses.values.filter { it.ledgerId == ledgerId && it.serverId in wanted }
    }

    override suspend fun findAnyByServerIds(serverIds: List<Long>): List<ExpenseEntity> {
        val wanted = serverIds.toSet()
        return expenses.values.filter { it.serverId in wanted }
    }

    override suspend fun insert(expense: ExpenseEntity): Long {
        val id = if (expense.id == 0L) nextId++ else expense.id
        expenses[id] = expense.copy(id = id)
        emit(expense.ledgerId)
        return id
    }

    override suspend fun insertAll(expenses: List<ExpenseEntity>): List<Long> {
        return expenses.map { insert(it) }
    }

    override suspend fun update(expense: ExpenseEntity) {
        expenses[expense.id] = expense
        emit(expense.ledgerId)
    }

    override suspend fun updateAll(expenses: List<ExpenseEntity>) {
        expenses.forEach { update(it) }
    }

    override suspend fun clear() {
        val touched = expenses.values.map { it.ledgerId }.toSet()
        expenses.clear()
        touched.forEach { emit(it) }
    }

    override suspend fun clearForLedger(ledgerId: String) {
        expenses.values
            .filter { it.ledgerId == ledgerId }
            .map { it.id }
            .forEach { expenses.remove(it) }
        emit(ledgerId)
    }

    private fun flowFor(ledgerId: String): MutableStateFlow<List<ExpenseEntity>> =
        flows.getOrPut(ledgerId) { MutableStateFlow(snapshot(ledgerId)) }

    private fun snapshot(ledgerId: String): List<ExpenseEntity> =
        expenses.values
            .filter { it.ledgerId == ledgerId && it.status == "confirmed" }
            .sortedByDescending { it.expenseTime ?: it.confirmedAt ?: it.createdAt }

    private fun emit(ledgerId: String) {
        flowFor(ledgerId).value = snapshot(ledgerId)
    }
}

private fun unsupported(): Nothing = error("Unexpected API call")
