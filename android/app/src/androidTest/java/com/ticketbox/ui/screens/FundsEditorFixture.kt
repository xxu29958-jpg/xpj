package com.ticketbox.ui.screens

import android.content.Context
import android.content.ContextWrapper
import androidx.room.Room
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.RepositoryGraph
import com.ticketbox.RepositoryGraphDependencies
import com.ticketbox.RepositoryGraphOutbox
import com.ticketbox.data.local.AppDatabase
import com.ticketbox.data.local.LocalSettingsStore
import com.ticketbox.data.remote.ApiClient
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.AccountPostingDto
import com.ticketbox.data.remote.dto.CreditPaymentDto
import com.ticketbox.data.remote.dto.FinancialAccountDto
import com.ticketbox.data.remote.dto.FinancialAccountReceiptDto
import com.ticketbox.data.repository.ApiServiceProvider
import com.ticketbox.data.repository.FundsCommandDispatcher
import com.ticketbox.data.repository.FundsRepository
import com.ticketbox.data.repository.LedgerRequestGuard
import com.ticketbox.data.repository.OutboxDrainEngine
import com.ticketbox.data.repository.OutboxRepository
import com.ticketbox.data.repository.toOutboxBinding
import com.ticketbox.domain.model.AccountChoice
import com.ticketbox.domain.model.ActivityCorrectionPart
import com.ticketbox.domain.model.CreditApplicationChoice
import com.ticketbox.domain.model.CreditApplicationHistory
import com.ticketbox.domain.model.CreditApplications
import com.ticketbox.domain.model.CreditDrawView
import com.ticketbox.domain.model.CreditFeeView
import com.ticketbox.domain.model.CreditTerms
import com.ticketbox.domain.model.EnvelopeAccount
import com.ticketbox.domain.model.EnvelopeMonth
import com.ticketbox.domain.model.EnvelopePurpose
import com.ticketbox.domain.model.Envelopes
import com.ticketbox.domain.model.ExistingDebtChoice
import com.ticketbox.domain.model.ExpenseFundingView
import com.ticketbox.domain.model.FundMovement
import com.ticketbox.domain.model.FundingViewPart
import com.ticketbox.domain.model.FundsOverview
import com.ticketbox.domain.model.InstallmentPeriodView
import com.ticketbox.domain.model.InstallmentView
import com.ticketbox.domain.model.Installments
import com.ticketbox.security.LocalSessionIdentity
import com.ticketbox.security.LocalSessionRecord
import com.ticketbox.security.LocalSessionStore
import com.ticketbox.security.SessionCredentialAdapter
import com.ticketbox.security.StoredSessionToken
import com.ticketbox.viewmodel.FundsViewModel
import java.lang.reflect.Proxy
import kotlinx.coroutines.flow.flowOf
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response

/** Production funds graph over in-memory Room; the session and every server answer are synthetic. */
internal class FundsEditorFixture(context: Context) : AutoCloseable {
    private val settingsContext = object : ContextWrapper(context) {
        override fun getApplicationContext(): Context = this
        override fun getSharedPreferences(name: String, mode: Int) = context.getSharedPreferences("funds-editor.$name", mode)
    }
    private val settings = LocalSettingsStore(settingsContext)
    private val database = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java).build()
    private val session = LocalSessionRecord(
        sessionGeneration = "funds-session", bindingRevision = "funds-binding",
        serverId = "50000000-0000-4000-8000-000000000001", dataGeneration = "50000000-0000-4000-8000-000000000002",
        serverUrl = "https://funds-editor.example.test", credential = StoredSessionToken(token = "synthetic-session"),
        identity = LocalSessionIdentity(accountPublicId = "50000000-0000-4000-8000-000000000003",
            devicePublicId = "50000000-0000-4000-8000-000000000004", accountName = "测试成员", ledgerId = "family",
            ledgerName = "测试账本", deviceName = "测试设备", role = "owner", boundAt = "2026-10-19T08:00:00Z"),
    )
    private val sessions = fundsProxy<LocalSessionStore> { method -> when (method) {
        "currentSession" -> session
        "observeSession" -> flowOf(session)
        "hasPersistedSessionState" -> true
        else -> error("Unexpected session method: $method")
    } }
    private val outbox = OutboxRepository(database.pendingMutationDao(), bindingProvider = { session.toOutboxBinding() }, onRowsDeleted = {})
    val network = FundsEditorNetwork()
    private val provider = ApiServiceProvider(object : ApiServiceFactory {
        override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = network.service
    }, sessions, SessionCredentialAdapter(sessions))
    val repository: FundsRepository = RepositoryGraph(RepositoryGraphDependencies(database, ApiClient(), settings, sessions,
        SessionCredentialAdapter(sessions), provider, RepositoryGraphOutbox(outbox, OutboxAdapterGraph()))).fundsRepository

    fun model(expenseId: Long? = null) = FundsViewModel(repository, expenseId)

    /** One real dispatch of the frozen original; the synthetic server answers with [FundsEditorNetwork.reply]. */
    suspend fun deliver() = OutboxDrainEngine(outbox, listOf(FundsCommandDispatcher(LedgerRequestGuard(provider))), maxAttempts = 1).drainOnce()

    override fun close() {
        database.close()
        settings.clear()
    }
}

internal class FundsEditorNetwork {
    /** The server's answer to a submitted command; null leaves the scenario without a submission. */
    var reply: HttpException? = null
    val service = object : ApiService by fundsProxy<ApiService>({ error("Unexpected remote method: $it") }) {
        override suspend fun fundsOverview() = FundsOverview("CNY", "2026-10-19", 1_362_210, 3_790, 1_358_420, 3, 0, 0)
        override suspend fun fundsAccounts() = listOf(bank, cash, huabei)
        override suspend fun fundsAccount(id: String) = fundsAccounts().single { it.publicId == id }
        override suspend fun fundsAccountChoices() = listOf(AccountChoice("cmb", "招商银行", "bank", "招商银行"),
            AccountChoice("alipay", "支付宝余额", "wallet", "支付宝"))
        override suspend fun existingFundDebts() = listOf(ExistingDebtChoice("debt-huabei", 2, "花呗旧账", 128_000, "CNY", "2026-08-01"))
        override suspend fun installments(id: String) = Installments(id, 7, "CNY", listOf(agreement), listOf(
            CreditDrawView("draw-phone", "手机分期", "2026-09-02", 360_000, 240_000, "agreement-phone"),
            CreditDrawView("draw-market", "超市", "2026-10-12", 5_000, 3_790, null),
        ))
        override suspend fun envelopes(month: String) = Envelopes("family", month, "CNY", 3, "2026-10-19T08:00:00Z", "2026-10-19",
            1_362_210, 300_000, 1_062_210, listOf(
                EnvelopeAccount("招商银行", "bank", "CNY", 1_276_210, 3, selected = true, canSelect = true),
                EnvelopeAccount("现金", "cash", "CNY", 86_000, 2, selected = false, canSelect = true),
            ), listOf(
                EnvelopePurpose("category:餐饮", "餐饮", true, 200_000, 150_000, 42_000, 0, 0, 108_000, 150_000),
                EnvelopePurpose("spending", "其他日常支出", true, 100_000, 100_000, 12_000, 3_790, 0, 88_000, 100_000),
                EnvelopePurpose("savings", "储蓄", false, null, 0, null, null, null, null, 0),
            ), listOf(EnvelopeMonth(month, 300_000)), emptyList())
        override suspend fun expenseFunding(id: Long) = ExpenseFundingView(id, 4, "CNY", 12_860, canEdit = true, parts = listOf(
            FundingViewPart("part-huabei", "huabei", 7, "花呗", "CNY", 12_860, 12_860, includedInOpening = false)))
        override suspend fun payCreditAccount(id: String, body: CreditPaymentDto, idempotencyKey: String): FinancialAccountReceiptDto =
            throw requireNotNull(reply)
        override suspend fun postFundsActivity(id: String, body: AccountPostingDto, idempotencyKey: String): FinancialAccountReceiptDto =
            throw requireNotNull(reply)
    }

    private val agreement = InstallmentView("agreement-phone", "series-phone", 1, "手机 12 期", "花呗账单", "2026-09-02",
        active = true, needsReview = false, remainingPrincipalMinor = 240_000, periods = listOf(
            InstallmentPeriodView("period-5", 5, "2026-11-02", 30_000, 450, 0, 0),
            InstallmentPeriodView("period-6", 6, "2026-12-02", 30_000, 450, 0, 0),
        ), drawPublicIds = listOf("draw-phone"))

    val bank = account("bank", "招商银行", "bank", 1_276_210, tail = "8821", rowVersion = 3).copy(movements = listOf(
        FundMovement("salary", "event-salary", "income", 865_000, "2026-10-15", "10 月工资", null, null, correctionParts = listOf(
            ActivityCorrectionPart("bank", 3, "招商银行", "CNY", 865_000))),
    ))
    val cash = account("cash", "现金", "cash", 86_000, rowVersion = 2)
    val huabei = account("huabei", "花呗", "credit", -3_790, rowVersion = 7).copy(
        creditTerms = CreditTerms(1_000_000, 960_000, "2026-10-18", 1, 9, "支付宝账单页"),
        feeObligations = listOf(CreditFeeView(901, "10 月分期手续费", "2026-10-02", 450, 450, "period-5")),
        creditApplications = CreditApplications(
            credits = listOf(CreditApplicationChoice("refund-shoes", "运动鞋退款", "2026-10-16", 12_900)),
            obligations = listOf(CreditApplicationChoice("draw-market", "超市", "2026-10-12", 3_790)),
            history = listOf(CreditApplicationHistory("applied-1", "耳机退款", "9 月账单", 5_000, 5_000, "退款已到账", "2026-09-20T08:00:00Z", null)),
        ),
        movements = listOf(
            FundMovement("draw", "event-draw", "credit_draw", -5_000, "2026-10-12", "超市", 77, null),
            FundMovement("repay", "event-repay", "repayment", 1_210, "2026-10-14", "10 月账单还款", null, "repayment-oct", canVoidRepayment = true),
        ),
    )

    private fun account(id: String, name: String, kind: String, balance: Long, tail: String? = null, rowVersion: Long) =
        FinancialAccountDto(publicId = id, name = name, ledgerId = "family", calendarRevision = 1, kind = kind, currencyCode = "CNY",
            visibility = "ledger", institution = null, tail = tail, rowVersion = rowVersion, archived = false, balanceMinor = balance,
            recordedChangeMinor = 0, openingDate = "2026-10-01", openingSource = "本人核对", debtPublicId = null, canEdit = true)
}

/** A refusal or conflict exactly as the server would encode it. */
internal fun fundsServerAnswer(status: Int, code: String, message: String) = HttpException(Response.error<Any>(status,
    """{"error":"$code","message":"$message"}""".toResponseBody("application/json".toMediaType())))

private inline fun <reified T> fundsProxy(crossinline answer: (String) -> Any?): T =
    Proxy.newProxyInstance(T::class.java.classLoader, arrayOf(T::class.java)) { _, method, _ -> answer(method.name) } as T
