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
import com.ticketbox.data.remote.dto.LedgerCreateRequestDto
import com.ticketbox.data.remote.dto.LedgerDto
import com.ticketbox.data.remote.dto.LedgerListResponseDto
import com.ticketbox.data.remote.dto.LedgerSwitchResponseDto
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
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.ResponseBody
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class LedgerRepositoryTest {

    @Test
    fun refreshLedgersPersistsJsonAndExposesSummaries() = runTest {
        val ledgers = listOf(
            ledgerDto("L_owner", "我的小票夹", role = "owner", isDefault = true),
            ledgerDto("L_house", "家庭账本", role = "viewer", isDefault = false),
        )
        val api = StubApi(listLedgersResult = LedgerListResponseDto(ledgers))
        val store = LedgerFakeSettingsStore().apply { saveServerUrl("https://api.zen70.cn") }
        val tokenStore = LedgerFakeTokenStore().apply { saveToken("old-token") }
        val dao = LedgerFakeDao()
        val repo = LedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = tokenStore,
            expenseDao = dao,
        )

        val refreshed = repo.refreshLedgers().getOrThrow()
        assertEquals(listOf("L_owner", "L_house"), refreshed.map { it.ledgerId })
        // Cached read returns the same list without hitting the network.
        api.listLedgersResult = null
        val cached = repo.cachedLedgers()
        assertEquals(listOf("L_owner", "L_house"), cached.map { it.ledgerId })
    }

    @Test
    fun createLedgerRejectsBlankNameWithChineseMessage() = runTest {
        val repo = makeRepo()
        val failure = repo.createLedger("   ").exceptionOrNull()
        assertNotNull(failure)
        assertTrue(failure.message!!.contains("请填写账本名称"))
    }

    @Test
    fun createLedgerRejectsOversizeNameWithChineseMessage() = runTest {
        val repo = makeRepo()
        val failure = repo.createLedger("帐".repeat(61)).exceptionOrNull()
        assertNotNull(failure)
        assertTrue(failure.message!!.contains("最多 60 个字"))
    }

    @Test
    fun switchLedgerRotatesTokenAndClearsTargetCacheFirst() = runTest {
        val newToken = "session-token-new"
        val api = StubApi(
            switchResult = LedgerSwitchResponseDto(
                sessionToken = newToken,
                ledger = ledgerDto("L_house", "家庭账本", role = "viewer"),
                accountName = "我",
                deviceName = "Pixel",
            ),
        )
        val store = LedgerFakeSettingsStore().apply { saveServerUrl("https://api.zen70.cn") }
        val tokenStore = LedgerFakeTokenStore().apply { saveToken("old-token") }
        val dao = LedgerFakeDao().apply {
            // Pre-seed the cache for both ledgers.
            insertEntity(ledgerEntity(id = 1, ledgerId = "L_owner", serverId = 100))
            insertEntity(ledgerEntity(id = 2, ledgerId = "L_house", serverId = 200))
        }
        val repo = LedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = tokenStore,
            expenseDao = dao,
        )

        val summary = repo.switchLedger("L_house").getOrThrow()
        assertEquals("L_house", summary.ledgerId)
        assertEquals(newToken, tokenStore.getToken())
        assertEquals("L_house", store.activeLedgerId())
        // Only the target ledger's rows are wiped; the other ledger keeps its cache.
        assertNull(dao.find(2))
        assertNotNull(dao.find(1))
    }

    @Test
    fun switchLedgerFailurePreservesOldToken() = runTest {
        val errorJson = "{\"error\":\"forbidden\",\"message\":\"无权访问该账本\"}"
        val api = StubApi(
            switchError = HttpException(
                Response.error<Any>(403, errorJson.toResponseBody("application/json".toMediaType())),
            ),
        )
        val store = LedgerFakeSettingsStore().apply { saveServerUrl("https://api.zen70.cn") }
        val tokenStore = LedgerFakeTokenStore().apply { saveToken("old-token") }
        val repo = LedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = tokenStore,
            expenseDao = LedgerFakeDao(),
        )

        val failure = repo.switchLedger("L_house").exceptionOrNull()
        assertNotNull(failure)
        assertEquals("old-token", tokenStore.getToken())
        assertNull(store.activeLedgerId())
        assertFalse(failure.message.isNullOrBlank())
    }

    private fun makeRepo(): LedgerRepository {
        val store = LedgerFakeSettingsStore().apply { saveServerUrl("https://api.zen70.cn") }
        val tokenStore = LedgerFakeTokenStore().apply { saveToken("t") }
        return LedgerRepository(
            apiClient = LedgerStubApiFactory(StubApi()),
            settingsStore = store,
            tokenStore = tokenStore,
            expenseDao = LedgerFakeDao(),
        )
    }

    private fun ledgerDto(
        id: String,
        name: String,
        role: String = "owner",
        isDefault: Boolean = false,
    ) = LedgerDto(
        ledgerId = id,
        name = name,
        role = role,
        isDefault = isDefault,
        createdAt = "2026-01-01T00:00:00Z",
        archivedAt = null,
    )
}

private class LedgerStubApiFactory(private val service: ApiService) : ApiServiceFactory {
    override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = service
}

private class StubApi(
    var listLedgersResult: LedgerListResponseDto? = null,
    var createResult: LedgerDto? = null,
    var switchResult: LedgerSwitchResponseDto? = null,
    var switchError: Throwable? = null,
) : ApiService {
    override suspend fun listLedgers(): LedgerListResponseDto {
        return listLedgersResult ?: LedgerListResponseDto(ledgers = emptyList())
    }

    override suspend fun createLedger(request: LedgerCreateRequestDto): LedgerDto {
        return createResult ?: LedgerDto(
            ledgerId = "L_new",
            name = request.name,
            role = "owner",
            isDefault = false,
            createdAt = "2026-01-01T00:00:00Z",
            archivedAt = null,
        )
    }

    override suspend fun switchLedger(ledgerId: String): LedgerSwitchResponseDto {
        switchError?.let { throw it }
        return switchResult ?: error("Unexpected switch call")
    }

    override suspend fun pairDevice(request: PairRequestDto): PairResponseDto = unsupported()
    override suspend fun checkAuth(): AuthCheckDto = unsupported()
    override suspend fun pendingExpenses(): List<ExpenseDto> = unsupported()
    override suspend fun confirmedExpenses(
        page: Int,
        pageSize: Int,
        month: String?,
        category: String?,
        timezone: String?,
    ): PaginatedExpensesDto = unsupported()
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
}

private class LedgerFakeSettingsStore : TicketboxSettingsStore {
    override val backgroundSettingsFlow: Flow<BackgroundSettings> = MutableStateFlow(BackgroundSettings())
    private var serverUrl: String? = null
    private var ledgerName: String? = null
    private var ledgersJson: String? = null
    private val ledgerIdFlow = MutableStateFlow<String?>(null)
    override fun serverUrl(): String? = serverUrl
    override fun appSkinKey(): String? = null
    override fun monthlyBudgetCents(): Long? = null
    override fun saveMonthlyBudgetCents(amountCents: Long?) = Unit
    override fun lastConfirmedSyncAt(): String? = null
    override fun accountName(): String? = null
    override fun ledgerName(): String? = ledgerName
    override fun activeLedgerId(): String? = ledgerIdFlow.value
    override fun activeLedgerName(): String? = ledgerName
    override fun availableLedgersJson(): String? = ledgersJson
    override fun observeActiveLedgerId(): Flow<String?> = ledgerIdFlow
    override fun saveActiveLedger(ledgerId: String, ledgerName: String) {
        ledgerIdFlow.value = ledgerId
        this.ledgerName = ledgerName
    }
    override fun saveAvailableLedgersJson(json: String?) { ledgersJson = json }
    override fun deviceName(): String? = null
    override fun role(): String? = null
    override fun boundAt(): String? = null
    override fun saveIdentity(
        accountName: String,
        ledgerId: String,
        ledgerName: String,
        deviceName: String,
        role: String,
        boundAt: String,
    ) {
        ledgerIdFlow.value = ledgerId
        this.ledgerName = ledgerName
    }
    override fun saveLastConfirmedSyncAt(value: String) = Unit
    override fun clearLastConfirmedSyncAt() = Unit
    override fun lastUploadAt(): String? = null
    override fun saveLastUploadAt(value: String) = Unit
    override fun saveAppSkinKey(skinKey: String) = Unit
    override fun saveServerUrl(serverUrl: String) {
        this.serverUrl = serverUrl.trim().trimEnd('/')
    }
    override fun isBound(): Boolean = !serverUrl.isNullOrBlank()
    override fun markUnlocked() = Unit
    override fun markBackgrounded() = Unit
    override fun requiresUnlock(): Boolean = false
    override fun clear() {
        serverUrl = null; ledgerIdFlow.value = null; ledgerName = null; ledgersJson = null
    }
}

private class LedgerFakeTokenStore : SessionTokenStore {
    private var token: String? = null
    override fun saveToken(token: String) { this.token = token }
    override fun getToken(): String? = token
    override fun clear() { token = null }
}

private class LedgerFakeDao : ExpenseDao {
    private val map = linkedMapOf<Long, ExpenseEntity>()
    private val flows = mutableMapOf<String, MutableStateFlow<List<ExpenseEntity>>>()
    fun insertEntity(entity: ExpenseEntity) { map[entity.id] = entity }
    fun find(id: Long): ExpenseEntity? = map[id]
    override fun observeConfirmed(ledgerId: String): Flow<List<ExpenseEntity>> = flowFor(ledgerId)
    override suspend fun getConfirmed(ledgerId: String): List<ExpenseEntity> = map.values.filter { it.ledgerId == ledgerId }
    override suspend fun findByServerId(ledgerId: String, serverId: Long): ExpenseEntity? =
        map.values.firstOrNull { it.ledgerId == ledgerId && it.serverId == serverId }
    override suspend fun findByServerIds(ledgerId: String, serverIds: List<Long>): List<ExpenseEntity> =
        map.values.filter { it.ledgerId == ledgerId && it.serverId in serverIds.toSet() }
    override suspend fun findAnyByServerIds(serverIds: List<Long>): List<ExpenseEntity> =
        map.values.filter { it.serverId in serverIds.toSet() }
    override suspend fun insert(expense: ExpenseEntity): Long {
        map[expense.id] = expense
        return expense.id
    }
    override suspend fun insertAll(expenses: List<ExpenseEntity>): List<Long> = expenses.map { insert(it) }
    override suspend fun update(expense: ExpenseEntity) { map[expense.id] = expense }
    override suspend fun updateAll(expenses: List<ExpenseEntity>) { expenses.forEach { update(it) } }
    override suspend fun clear() { map.clear() }
    override suspend fun clearForLedger(ledgerId: String) {
        val ids = map.values.filter { it.ledgerId == ledgerId }.map { it.id }
        ids.forEach { map.remove(it) }
    }
    private fun flowFor(ledgerId: String): MutableStateFlow<List<ExpenseEntity>> =
        flows.getOrPut(ledgerId) { MutableStateFlow(emptyList()) }
}

private fun unsupported(): Nothing = error("Unexpected API call")

private fun ledgerEntity(id: Long, ledgerId: String, serverId: Long): ExpenseEntity = ExpenseEntity(
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
)
