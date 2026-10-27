package com.ticketbox.data.repository

import com.ticketbox.BuildConfig
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import com.ticketbox.data.remote.dto.MerchantAliasDto
import com.ticketbox.data.remote.dto.MerchantAliasUpdateRequest
import com.ticketbox.data.remote.dto.RecurringCandidateConfirmRequestDto
import com.ticketbox.data.remote.dto.RecurringItemDto
import android.util.Log
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.test.runTest
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody
import okio.Buffer
import okio.BufferedSource
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.Implementation
import org.robolectric.annotation.Implements
import org.robolectric.shadows.ShadowLog
import retrofit2.HttpException
import java.io.IOException
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertSame
import kotlin.test.assertTrue

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], manifest = Config.NONE)
class NetworkErrorReportingTest {
    private val handler = NetworkErrorHandler({ "https://example.test" }, "ReportingProbe")

    @Before
    fun clearLog() = ShadowLog.clear()

    @Test
    fun realDecodeCarriesBodyIdConflictAndCauseToFinalLogWithOneBodyRead() = runTest {
        val body = CountingBody("""{"error":"tag_conflict","request_id":"body-id","message":"private financial text",
            "conflict_tag_public_id":"tag-id","conflict_tag_row_version":7}""")
        val original = httpError(body, "header-id", 409)
        val failure = handler.safeCall<Unit> { throw original }.exceptionOrNull() as RepositoryException
        assertEquals("tag_conflict", failure.errorCode)
        assertEquals(7L, failure.conflictTagRowVersion)
        assertEquals(409, failure.httpStatusCode)
        assertSame(original, failure.cause)
        assertEquals(1, body.reads)
        val output = finalLog()
        assertTrue(output.contains("request_id=body-id"))
        assertTrue(output.contains("request_id_mismatch=true header_request_id=header-id"))
        assertTrue(output.contains("code=tag_conflict"))
        assertFalse(output.contains("private financial text"))
        assertLocated(output)
    }

    @Test
    fun oldMalformedAndHeaderOnlyResponsesKeepFallbackAndNeverInventServerIds() {
        for (body in listOf("""{"error":"server_error"}""", "invalid JSON")) {
            val withHeader = handler.httpFailure(httpError(CountingBody(body), "header-only"))
            assertEquals(503, withHeader.httpStatusCode)
            assertTrue(finalLog().contains("request_id=header-only"))
        }
        val old = handler.httpFailure(httpError(CountingBody("""{"error":"server_error"}""")))
        assertEquals("server_error", old.errorCode)
        assertTrue(finalLog().contains("request_id=absent"))
    }

    @Test
    fun transportAndUnexpectedErrorsKeepResultsAndCausesWithoutPrintingSecrets() = runTest {
        val secrets = listOf("synthetic-bearer", "synthetic-upload", "87654321", "synthetic-password")
        val root = IOException("Authorization: Bearer ${secrets[0]} password=${secrets[3]}")
        val failure = IllegalStateException("https://host.test/u/${secrets[1]}#pairing=${secrets[2]}", root)
        for (original in listOf(root, failure)) {
            val result = handler.safeCall<Unit> { throw original }
            val reported = result.exceptionOrNull() as RepositoryException
            assertOriginalCause(original, reported.cause)
            assertNull(reported.httpStatusCode)
        }
        logNetworkWarning("Authorization: Bearer ${secrets[0]} url=https://host.test/u/${secrets[1]} " +
            "pairing=${secrets[2]} password=${secrets[3]}", failure)
        val output = finalLog()
        assertTrue(output.contains("IOException") && output.contains("IllegalStateException"))
        assertTrue(secrets.none(output::contains))
        assertLocated(output)
        assertTrue(ShadowLog.getLogsForTag("TicketboxNetwork").all { it.throwable == null })
    }

    @Test
    fun cancellationAndExistingBusinessFailureKeepOriginalObjects() = runTest {
        val cancellation = CancellationException("cancel probe")
        try {
            handler.safeCall<Unit> { throw cancellation }
            error("cancellation was swallowed")
        } catch (actual: CancellationException) {
            assertOriginalCause(cancellation, actual)
        }
        val refusal = RepositoryException("existing business refusal")
        assertSame(refusal, handler.safeCall<Unit> { throw refusal }.exceptionOrNull())
        assertTrue(ShadowLog.getLogsForTag("TicketboxNetwork").isEmpty())
    }

    @Test
    @Config(shadows = [FailedLogSink::class])
    fun failedLogSinkDoesNotReplaceTheOriginalNetworkFailureOrRetryIt() = runTest {
        val original = IOException("synthetic failure")
        var attempts = 0
        val result = handler.safeCall<Unit> { attempts += 1; throw original }
        assertEquals(1, attempts)
        assertOriginalCause(original, result.exceptionOrNull()?.cause)
    }

    @Test
    fun aliasReplayFailureReportsWithoutSettlingOrRetryingOriginal() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao = dao)
        val payload = """{"expected_row_version":0,"enabled":false}"""
        val originalId = outbox.enqueue(PendingMutationType.UpdateMerchantAlias, "merchant_alias:original", payload,
            1L, idempotencyKey = "original-key")
        var attempts = 0
        val api = object : ApiService by FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0) {
            override suspend fun updateMerchantAlias(
                publicId: String, request: MerchantAliasUpdateRequest, idempotencyKey: String?,
            ): MerchantAliasDto {
                attempts += 1
                throw IllegalStateException("password=synthetic-alias-secret", IOException("private financial text"))
            }
        }
        val adapter = Moshi.Builder().add(KotlinJsonAdapterFactory()).build().adapter(MerchantAliasUpdateRequest::class.java)
        dao.runnableBatches += listOf(dao.rows.keys.single())
        val summary = OutboxDrainEngine(outbox, listOf(UpdateMerchantAliasDispatcher({ api }, adapter))).drainOnce()

        assertEquals(1, attempts)
        assertEquals(0, summary.done)
        assertEquals(1, summary.failures)
        val original = dao.rows.getValue(originalId)
        assertEquals(PendingMutationStatus.Failed.wireValue, original.status)
        assertEquals(payload, original.payload)
        assertEquals("original-key", original.idempotencyKey)
        val output = finalLog()
        assertTrue(output.contains("operation=UpdateMerchantAlias"))
        assertTrue(output.contains("UpdateMerchantAliasDispatcher.kt:"))
        assertTrue(output.contains("source_tree_sha256=${BuildConfig.SOURCE_FINGERPRINT}"))
        assertTrue(output.contains("IllegalStateException") && output.contains("IOException"))
        assertFalse(output.contains("synthetic-alias-secret") || output.contains("private financial text"))
        assertFalse(original.lastError.orEmpty().contains("synthetic-alias-secret"))
        assertTrue(ShadowLog.getLogsForTag("TicketboxNetwork").all { it.throwable == null })
    }

    @Test
    fun debtCreateFailureReportsSafelyWithoutSettlingTheOriginal() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao = dao)
        val adapter = com.ticketbox.OutboxAdapterGraph().debt.debtCreateAdapter
        val payload = adapter.toJson(DebtCreateOutboxPayload(1, "CNY", "session", "binding",
            DebtCreateOutboxRequest("i_owe", "external", "对方", 12_345L)))
        val originalId = outbox.enqueue(PendingMutationType.CreateDebt, "debt_create:original-key", payload,
            0L, idempotencyKey = "original-key")
        var attempts = 0
        val api = object : ApiService by FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0) {
            override suspend fun createDebt(request: com.ticketbox.data.remote.dto.DebtCreateRequestDto,
                idempotencyKey: String?): com.ticketbox.data.remote.dto.DebtDto {
                attempts++
                throw IllegalStateException("password=synthetic-debt-secret", IOException("private principal text"))
            }
        }
        dao.runnableBatches += listOf(dao.rows.keys.single())
        val summary = OutboxDrainEngine(outbox, listOf(CreateDebtDispatcher({ api }, adapter))).drainOnce()
        assertEquals(1, attempts)
        assertEquals(0, summary.done)
        assertEquals(1, summary.failures)
        val original = dao.rows.getValue(originalId)
        assertEquals(payload, original.payload)
        assertEquals("original-key", original.idempotencyKey)
        val output = finalLog()
        assertTrue(output.contains("operation=Debt create response unverified"))
        assertTrue(output.contains("CreateDebtDispatcher.kt:"))
        assertFalse(output.contains("synthetic-debt-secret") || output.contains("private principal text"))
        assertTrue(ShadowLog.getLogsForTag("TicketboxNetwork").all { it.throwable == null })
    }

    @Test
    fun debtLocalPublicationFailureReportsWithoutInventingAcceptance() = runTest {
        val fixture = DebtCreationFixture()
        fixture.dao.beforeInsert = { throw IllegalStateException("password=private-local-secret") }
        val result = fixture.save(creationKey = "retained-original")
        assertEquals("debt_create_local_save_failed", (result.exceptionOrNull() as RepositoryException).errorCode)
        assertTrue(fixture.dao.rows.isEmpty())
        assertTrue(fixture.api.calls.isEmpty())
        assertTrue(fixture.queueDepthAtSchedule.isEmpty())
        val output = finalLog()
        assertTrue(output.contains("operation=Debt create local acceptance unverified"))
        assertTrue(output.contains("DebtCreationRepository.kt:"))
        assertFalse(output.contains("private-local-secret"))
        assertTrue(ShadowLog.getLogsForTag("TicketboxNetwork").all { it.throwable == null })
        fixture.dao.beforeInsert = null
        fixture.save(creationKey = "retained-original").getOrThrow()
        assertEquals("retained-original", fixture.dao.rows.values.single().idempotencyKey)
        assertTrue(fixture.api.calls.isEmpty())
    }

    @Test
    fun candidateReplayFailureReportsSafelyAndKeepsItsOriginalCommand() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao = dao)
        val adapter = Moshi.Builder().add(KotlinJsonAdapterFactory()).build().adapter(RecurringCandidatePayload::class.java)
        val payload = adapter.toJson(RecurringCandidatePayload(RecurringCandidateConfirmRequestDto(
            merchant = "原建议", amountCents = 2400, homeCurrencyCode = "JPY"), "UTC"))
        val originalId = outbox.enqueue(PendingMutationType.ConfirmRecurringCandidate, "recurring_candidate:original-key",
            payload, 0L, idempotencyKey = "original-key")
        var attempts = 0
        val api = object : ApiService by FakeApiService(mutableListOf(), 0) {
            override suspend fun confirmRecurringCandidate(request: RecurringCandidateConfirmRequestDto,
                timezone: String?, idempotencyKey: String): RecurringItemDto {
                attempts++
                throw IllegalStateException("password=synthetic-adoption-secret", IOException("private financial text"))
            }
        }
        dao.runnableBatches += listOf(dao.rows.keys.single())
        val summary = OutboxDrainEngine(outbox, listOf(ConfirmRecurringCandidateDispatcher({ api }, adapter))).drainOnce()
        val original = dao.rows.getValue(originalId)
        assertEquals(1, attempts)
        assertEquals(0, summary.done)
        assertEquals(1, summary.failures)
        assertEquals(PendingMutationStatus.Failed.wireValue, original.status)
        assertEquals(payload, original.payload)
        assertEquals("original-key", original.idempotencyKey)
        assertEquals(RECURRING_RECEIPT_UNVERIFIED, original.lastError)
        val output = finalLog()
        assertTrue(output.contains("operation=ConfirmRecurringCandidate") && output.contains("ConfirmRecurringCandidateDispatcher.kt:"))
        assertTrue(output.contains("source_tree_sha256=${BuildConfig.SOURCE_FINGERPRINT}"))
        assertTrue(output.contains("IllegalStateException") && output.contains("IOException"))
        assertFalse(output.contains("synthetic-adoption-secret") || output.contains("private financial text"))
        assertTrue(ShadowLog.getLogsForTag("TicketboxNetwork").all { it.throwable == null })
    }

    @Test
    fun debtLinkReplayFailureReportsSafelyAndKeepsItsOriginalCommand() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao = dao)
        val adapters = com.ticketbox.OutboxAdapterGraph()
        val payload = adapters.goalDebtEditAdapter.toJson(DebtGoalEditPayload("原关联任务",
            com.ticketbox.data.remote.dto.DebtGoalLinksReplaceRequestDto(7, listOf("debt-original")),
            mapOf("debt-original" to "原选择")))
        val id = outbox.enqueue(PendingMutationType.ReplaceGoalDebtLinks, "goal:original", payload, 7L, "original-links-key")
        var attempts = 0
        val api = object : ApiService by FakeApiService(mutableListOf(), 0) {
            override suspend fun replaceGoalDebtLinks(publicId: String,
                request: com.ticketbox.data.remote.dto.DebtGoalLinksReplaceRequestDto, idempotencyKey: String?, timezone: String?):
                com.ticketbox.data.remote.dto.GoalDto {
                attempts++
                throw IllegalStateException("password=synthetic-links-secret", IOException("private financial text"))
            }
        }
        dao.runnableBatches += listOf(dao.rows.keys.single())
        val summary = OutboxDrainEngine(outbox, listOf(DebtGoalEditDispatcher({ api },
            adapters.goalDebtEditAdapter, adapters.goalReceiptAdapter) { error("Unconfirmed results cannot invalidate reads") })).drainOnce()
        val original = dao.rows.getValue(id)
        assertEquals(1, attempts)
        assertEquals(0, summary.done)
        assertEquals(1, summary.failures)
        assertEquals(payload, original.payload)
        assertEquals(7L, original.expectedRowVersion)
        assertEquals("original-links-key", original.idempotencyKey)
        assertEquals("目标修改的结果无法确认，已保留原提交，请核对。", original.lastError)
        val output = finalLog()
        assertTrue(output.contains("operation=ReplaceGoalDebtLinks") && output.contains("DebtGoalEditSubmission.kt:"))
        assertTrue(output.contains("IllegalStateException") && output.contains("IOException"))
        assertFalse(output.contains("synthetic-links-secret") || output.contains("private financial text"))
        assertTrue(ShadowLog.getLogsForTag("TicketboxNetwork").all { it.throwable == null })
    }

    @Test
    fun confirmReplayFailureReportsSafelyAndKeepsItsOriginalCommand() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao = dao)
        val payload = """{"expected_row_version":0}"""
        val originalId = outbox.enqueue(PendingMutationType.ConfirmExpense, "expense:42", payload,
            7L, idempotencyKey = "original-confirm-key")
        var attempts = 0
        val api = object : ApiService by FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0) {
            override suspend fun confirmExpense(id: String, request: ExpenseStateTokenRequest, idempotencyKey: String?): ExpenseDto {
                attempts += 1
                assertEquals("42", id)
                assertEquals(7L, request.expectedRowVersion)
                assertEquals("original-confirm-key", idempotencyKey)
                throw IllegalStateException("password=synthetic-confirm-secret", IOException("private financial text"))
            }
        }
        val adapter = Moshi.Builder().add(KotlinJsonAdapterFactory()).build().adapter(ExpenseStateTokenRequest::class.java)
        dao.runnableBatches += listOf(dao.rows.keys.single())
        val summary = OutboxDrainEngine(outbox, listOf(ConfirmExpenseDispatcher({ api }, adapter) { _, _ ->
            error("A failed response must not publish a fact")
        })).drainOnce()
        assertEquals(1, attempts)
        assertEquals(0, summary.done)
        assertEquals(1, summary.failures)
        val original = dao.rows.getValue(originalId)
        assertEquals(PendingMutationStatus.Failed.wireValue, original.status)
        assertEquals(payload, original.payload)
        assertEquals(7L, original.expectedRowVersion)
        assertEquals("original-confirm-key", original.idempotencyKey)
        assertEquals("确认结果暂时无法核实，请稍后重试。原提交仍保留。", original.lastError)
        val output = finalLog()
        assertTrue(output.contains("operation=ConfirmExpense"))
        assertTrue(output.contains("ConfirmExpenseDispatcher.kt:"))
        assertTrue(output.contains("IllegalStateException") && output.contains("IOException"))
        assertFalse(output.contains("synthetic-confirm-secret") || output.contains("private financial text"))
        assertTrue(ShadowLog.getLogsForTag("TicketboxNetwork").all { it.throwable == null })
    }

    @Test
    fun fundsReplayFailureReportsSafelyWithoutRetryingOrConsumingTheCommand() = runTest {
        var unavailable = true
        var receiptLedger = "family"
        val api = object : ApiService by FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0) {
            override suspend fun editFundsAccount(id: String, request: com.ticketbox.data.remote.dto.FinancialAccountEditDto,
                key: String): com.ticketbox.data.remote.dto.FinancialAccountReceiptDto {
                assertEquals("reviewed-account", id)
                assertEquals(7L, request.expectedRowVersion)
                assertEquals("original-funds-key", key)
                if (unavailable) throw IllegalStateException("password=synthetic-funds-secret", IOException("private financial text"))
                // A legacy server's growing read model must never be copied into Room.
                return requireNotNull(FundsWire.accountReceipt.fromJson("""{
                    "public_id":"reviewed-account","ledger_id":"$receiptLedger","row_version":8,
                    "currency_code":"CNY","balance_minor":12345,"recorded_change_minor":12345,
                    "movements":[{"note":"old account history"}],"fee_obligations":[{"note":"old fee history"}]
                }"""))
            }
        }
        val factory = object : com.ticketbox.data.remote.ApiServiceFactory {
            override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = api
        }
        val provider = testApiServiceProvider(factory, TestSessionFixture().apply { saveToken("session-token") })
        val guard = LedgerRequestGuard(provider)
        val command = FundsCommand(binding = requireNotNull(guard.captureLogicalBinding()), accountId = "reviewed-account",
            edit = com.ticketbox.data.remote.dto.FinancialAccountEditDto(7L, "本人核对", null, null, false))
        val payload = FundsWire.command.toJson(command)
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao, bindingProvider = { provider.currentSession().toOutboxBinding() })
        val id = outbox.enqueue(PendingMutationType.FinancialAccountCommand, command.target("original-funds-key"), payload,
            command.version, idempotencyKey = "original-funds-key")
        dao.runnableBatches += listOf(id)
        val result = OutboxDrainEngine(outbox, listOf(FundsCommandDispatcher(guard))).drainOnce()
        assertEquals(0, result.done)
        assertEquals(1, result.failures)
        val original = dao.rows.getValue(id)
        assertEquals(PendingMutationStatus.Failed.wireValue, original.status)
        assertEquals(payload, original.payload)
        assertEquals("original-funds-key", original.idempotencyKey)
        assertEquals(7L, original.expectedRowVersion)
        assertNull(original.receiptJson)
        val output = finalLog()
        assertTrue(output.contains("FundsCommand.kt:") && output.contains("IllegalStateException"))
        assertFalse(output.contains("synthetic-funds-secret") || output.contains("private financial text"))
        unavailable = false
        assertTrue(outbox.resolveFailed(id, FailedResolution.Retry(), guard.bindExact(command.binding)))
        dao.runnableBatches += listOf(id)
        assertEquals(0, OutboxDrainEngine(outbox, listOf(FundsCommandDispatcher(guard))).drainOnce().done)
        val foreign = dao.rows.getValue(id)
        assertEquals(PendingMutationStatus.Failed.wireValue, foreign.status)
        assertEquals(payload, foreign.payload)
        assertEquals("original-funds-key", foreign.idempotencyKey)
        assertNull(foreign.receiptJson)
        receiptLedger = command.binding.ledgerId
        assertTrue(outbox.resolveFailed(id, FailedResolution.Retry(), guard.bindExact(command.binding)))
        dao.runnableBatches += listOf(id)
        assertEquals(1, OutboxDrainEngine(outbox, listOf(FundsCommandDispatcher(guard))).drainOnce().done)
        val accepted = dao.rows.getValue(id)
        assertEquals(payload, accepted.payload)
        assertEquals("original-funds-key", accepted.idempotencyKey)
        val receipt = requireNotNull(accepted.receiptJson)
        assertEquals(8L, FundsWire.accountReceipt.fromJson(receipt)?.rowVersion)
        assertEquals(12345L, FundsWire.accountReceipt.fromJson(receipt)?.balanceMinor)
        assertFalse(receipt.contains("movements") || receipt.contains("old account history") || receipt.contains("fee_obligations"))
    }

    private fun assertLocated(output: String) {
        assertTrue(output.contains("operation=ReportingProbe"))
        assertTrue(output.contains("source_tree_sha256=${BuildConfig.SOURCE_FINGERPRINT}"))
        assertTrue(BuildConfig.SOURCE_FINGERPRINT.matches(Regex("[a-f0-9]{64}")))
        assertTrue(output.contains("NetworkErrorReportingTest.kt:"))
        assertTrue(output.contains("reported_at:"))
    }

    private fun assertOriginalCause(original: Throwable, actual: Throwable?) {
        // Coroutine stacktrace recovery may copy an exception across withContext,
        // retaining the original in its cause chain. That existing behavior stays intact.
        assertTrue(generateSequence(actual) { it.cause }.take(16).any { it === original })
    }

    private fun finalLog(): String = ShadowLog.getLogsForTag("TicketboxNetwork")
        .joinToString("\n") { assertNotNull(it.msg) }

    private class CountingBody(private val text: String) : ResponseBody() {
        var reads = 0
        override fun contentType() = "application/json".toMediaTypeOrNull()
        override fun contentLength() = text.toByteArray().size.toLong()
        override fun source(): BufferedSource {
            reads += 1
            return Buffer().writeUtf8(text)
        }
    }

    private fun httpError(body: ResponseBody, requestId: String? = null, status: Int = 503): HttpException {
        val raw = Response.Builder().protocol(Protocol.HTTP_1_1)
            .request(Request.Builder().url("https://example.test/u/synthetic-upload").build())
            .code(status).message("test").apply { if (requestId != null) header("X-Request-ID", requestId) }.build()
        return HttpException(retrofit2.Response.error<Unit>(body, raw))
    }
}

@Implements(Log::class)
class FailedLogSink {
    companion object {
        @JvmStatic
        @Implementation
        fun w(tag: String?, message: String?): Int {
            if (tag == "TicketboxNetwork") error("synthetic log output failure")
            return 0
        }
    }
}
