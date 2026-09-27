package com.ticketbox.data.repository

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.AppDatabase
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.*
import com.ticketbox.security.*
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.runBlocking
import java.io.IOException
import java.net.ConnectException
import javax.net.ssl.SSLHandshakeException
import com.squareup.moshi.JsonEncodingException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import java.lang.reflect.Proxy
import java.time.Clock
import java.time.Duration
import java.time.Instant
import java.time.ZoneOffset
import org.junit.After
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response

@RunWith(AndroidJUnit4::class)
class MonthlyArrangementRoomContinuityTest {
    private val context: Context = ApplicationProvider.getApplicationContext()
    private val name = "monthly-arrangement-continuity.db"
    private var db: AppDatabase? = null
    private val adapters = OutboxAdapterGraph()
    private var clock = Clock.fixed(Instant.parse("2026-09-27T00:00:00Z"), ZoneOffset.UTC)
    private val session = MutableStateFlow(LocalSessionRecord(sessionGeneration = "arrangement-session", bindingRevision = "arrangement-binding",
        serverId = "30000000-0000-4000-8000-000000000001", dataGeneration = "30000000-0000-4000-8000-000000000002",
        serverUrl = "https://arrangement.example.test", credential = StoredSessionToken("synthetic-test-token"),
        identity = LocalSessionIdentity(accountPublicId = "30000000-0000-4000-8000-000000000003",
            devicePublicId = "30000000-0000-4000-8000-000000000004", accountName = "成员", ledgerId = "owner",
            ledgerName = "账本", deviceName = "设备", role = "owner", boundAt = "2026-09-27T00:00:00Z")))
    private val sessions = arrangementProxy<LocalSessionStore> { method -> when (method) {
        "currentSession" -> session.value; "observeSession" -> session; "hasPersistedSessionState" -> true
        else -> error("Unexpected session method $method")
    } }
    private var offline = false
    private var readFailure: Exception? = null
    private var delayedRead: CompletableDeferred<Unit>? = null
    private val readStarted = CompletableDeferred<Unit>()
    private var loseAck = true
    private var conflict = false
    private var fact: MonthlyArrangementDto? = null
    private val receipts = mutableMapOf<String, MonthlyArrangementDto>()
    private val snapshots = mutableMapOf<String, String>()
    private val calls = mutableListOf<Pair<MonthlyArrangementSaveRequest, String>>()
    private val api = object : ApiService by arrangementProxy<ApiService>({ error("Unexpected API method $it") }) {
        override suspend fun monthlyArrangement(month: String): MonthlyArrangementResponseDto {
            val response = MonthlyArrangementResponseDto(session.value.identity.ledgerId, month, fact)
            delayedRead?.let { readStarted.complete(Unit); it.await(); return response }
            readFailure?.let { throw it }
            if (offline) throw ConnectException("offline")
            return MonthlyArrangementResponseDto(session.value.identity.ledgerId, month, fact)
        }
        override suspend fun monthlyArrangementHistory(month: String, beforeVersion: Long?, limit: Int): MonthlyArrangementHistoryDto {
            readFailure?.let { throw it }
            if (offline) throw ConnectException("offline")
            val items = fact?.let { listOf(MonthlyArrangementHistoryItemDto(it.rowVersion, it.updatedAt,
                it.homeCurrencyCode, it.savingsTargetCents, it.reservedBufferCents)) } ?: emptyList()
            return MonthlyArrangementHistoryDto(session.value.identity.ledgerId, month, items, null)
        }
        override suspend fun saveMonthlyArrangement(month: String, request: MonthlyArrangementSaveRequest, idempotencyKey: String): MonthlyArrangementDto {
            calls += request to idempotencyKey
            receipts[idempotencyKey]?.let { return it }
            if (conflict) throw HttpException(Response.error<MonthlyArrangementDto>(409,
                """{"error":"state_conflict","message":"另一端已修改安排。"}""".toResponseBody()))
            val accepted = MonthlyArrangementDto("owner", month, request.homeCurrencyCode, request.savingsTargetCents,
                request.reservedBufferCents, (request.expectedRowVersion ?: 0) + 1, "2026-09-27T00:00:00Z")
            receipts[idempotencyKey] = accepted; fact = accepted
            if (loseAck) throw IOException("lost ACK after server commit")
            return accepted
        }
    }
    private val provider = ApiServiceProvider(object : ApiServiceFactory {
        override fun create(baseUrl: String, tokenProvider: () -> String?) = api
    }, sessions, SessionCredentialAdapter(sessions))
    private lateinit var outbox: OutboxRepository
    private lateinit var coordinator: LocalLedgerSessionCoordinator
    private fun reopen(): MonthlyArrangementRepository {
        db?.close()
        val opened = Room.databaseBuilder(context, AppDatabase::class.java, name).build().also { db = it }
        outbox = OutboxRepository(opened.pendingMutationDao(), clock, onRowsDeleted = {}, bindingProvider = { session.value.toOutboxBinding() })
        val settings = arrangementProxy<TicketboxSettingsStore> { error("Unexpected settings method $it") }
        coordinator = LocalLedgerSessionCoordinator(settings, sessions, opened.expenseDao(), outbox)
        return MonthlyArrangementRepository(provider, outbox, opened.monthlyArrangementCacheDao(), adapters,
            { key, stamp -> snapshots[key] = stamp }, coordinator)
    }
    private fun binding() = requireNotNull(LedgerRequestGuard(provider).captureLogicalBinding())
    private suspend fun drain() = OutboxDrainEngine(outbox, listOf(SaveMonthlyArrangementDispatcher({ api },
        adapters.arrangementSaveAdapter, adapters.arrangementReceiptAdapter)), now = clock::millis).drainOnce()
    @After fun close() { db?.close(); context.deleteDatabase(name) }
    @Test fun malformedJsonAndTlsFailureCannotBecomeCachedSuccess() = runBlocking {
        loseAck = false
        val original = binding()
        val repository = reopen()
        val draft = MonthlyArrangementDraft("JPY", "1200", "300", null, true)
        repository.storeArrangementDraft(original, "2026-09", draft)
        repository.arrangement(original, "2026-09").getOrThrow()
        repository.enqueueArrangement(original, "2026-09", draft.request()).getOrThrow()
        assertEquals(1, drain().done)
        repository.arrangementHistory(original, "2026-09").getOrThrow()
        val before = requireNotNull(db).pendingMutationDao().allRows()
        val draftBefore = requireNotNull(db).monthlyArrangementCacheDao().read(monthlyArrangementPersistentBindingKey(original), "2026-09", "draft")
        for (failure in listOf(JsonEncodingException("malformed JSON"), SSLHandshakeException("TLS rejected"))) {
            readFailure = failure
            assertTrue(repository.arrangement(original, "2026-09").isFailure)
            assertTrue(repository.arrangementHistory(original, "2026-09").isFailure)
        }
        assertEquals(draft, repository.arrangementDraft(original, "2026-09"))
        assertEquals(draftBefore, requireNotNull(db).monthlyArrangementCacheDao().read(monthlyArrangementPersistentBindingKey(original), "2026-09", "draft"))
        assertEquals(before, requireNotNull(db).pendingMutationDao().allRows())
    }
    @Test fun accessRefusalSurvivesRoomReopenWithoutLosingOriginalIntentOrReceipt() = runBlocking {
        loseAck = false
        val original = binding()
        var repository = reopen()
        val draft = MonthlyArrangementDraft("JPY", "1200", "300", null, true)
        repository.storeArrangementDraft(original, "2026-09", draft)
        repository.arrangement(original, "2026-09").getOrThrow()
        repository.enqueueArrangement(original, "2026-09", draft.request()).getOrThrow()
        assertEquals(1, drain().done)
        repository.arrangementHistory(original, "2026-09").getOrThrow()
        val before = requireNotNull(db).pendingMutationDao().allRows()
        val draftBefore = requireNotNull(db).monthlyArrangementCacheDao().read(monthlyArrangementPersistentBindingKey(original), "2026-09", "draft")
        readFailure = HttpException(Response.error<MonthlyArrangementResponseDto>(403,
            """{"error":"forbidden","message":"无权读取账本。"}""".toResponseBody()))
        assertEquals(403, (repository.arrangement(original, "2026-09").exceptionOrNull() as RepositoryException).httpStatusCode)
        readFailure = null
        offline = true
        repository = reopen()
        assertTrue(repository.arrangement(original, "2026-09").isFailure)
        assertTrue(repository.arrangementHistory(original, "2026-09").isFailure)
        assertEquals(draft, repository.arrangementDraft(original, "2026-09"))
        assertEquals(draftBefore, requireNotNull(db).monthlyArrangementCacheDao().read(monthlyArrangementPersistentBindingKey(original), "2026-09", "draft"))
        assertEquals(before, requireNotNull(db).pendingMutationDao().allRows())
        assertTrue(repository.observeArrangements(original).first().single().isConfirmed)
    }
    @Test fun refusedAccessPreventsAnEarlierSuccessfulGetFromRepublishing() = runBlocking {
        val original = binding()
        val repository = reopen()
        repository.arrangement(original, "2026-09").getOrThrow()
        val release = CompletableDeferred<Unit>()
        delayedRead = release
        val oldRead = async { repository.arrangement(original, "2026-09") }
        readStarted.await()
        delayedRead = null
        readFailure = HttpException(Response.error<MonthlyArrangementHistoryDto>(403,
            """{"error":"forbidden"}""".toResponseBody()))
        assertTrue(repository.arrangementHistory(original, "2026-09").isFailure)
        val stampsAtRefusal = snapshots.toMap()
        release.complete(Unit)
        assertTrue(oldRead.await().isFailure)
        assertEquals(stampsAtRefusal, snapshots)
        readFailure = null
        offline = true
        assertTrue(reopen().arrangement(original, "2026-09").isFailure)
    }
    @Test fun receiptAloneCannotCreateAnOfflineQuery() = runBlocking {
        loseAck = false
        val original = binding()
        var repository = reopen()
        repository.enqueueArrangement(original, "2026-09", MonthlyArrangementSaveRequest("JPY", 1200, 300)).getOrThrow()
        assertEquals(1, drain().done)
        offline = true
        repository = reopen()
        assertTrue(repository.arrangement(original, "2026-09").isFailure)
        assertTrue(repository.observeArrangements(original).first().single().isConfirmed)
    }
    @Test fun explicitCacheClearingRetiresQueriesAndKeepsDraftAndReceiptBytes() = runBlocking {
        loseAck = false
        val original = binding()
        var repository = reopen()
        val draft = MonthlyArrangementDraft("JPY", "1200", "300", null, true)
        repository.storeArrangementDraft(original, "2026-09", draft)
        repository.enqueueArrangement(original, "2026-09", draft.request()).getOrThrow()
        assertEquals(1, drain().done)
        val before = requireNotNull(db).pendingMutationDao().allRows()
        val key = monthlyArrangementPersistentBindingKey(original)
        val draftBefore = requireNotNull(db).monthlyArrangementCacheDao().read(key, "2026-09", "draft")
        val otherKey = monthlyArrangementPersistentBindingKey(original.copy(ledgerId = "owner-other"))
        val otherDraft = requireNotNull(draftBefore).copy(bindingKey = otherKey)
        requireNotNull(db).monthlyArrangementCacheDao().write(otherDraft)
        for (allLedgers in listOf(false, true)) {
            offline = false
            repository.arrangement(original, "2026-09").getOrThrow()
            repository.arrangementHistory(original, "2026-09").getOrThrow()
            val otherSaved = requireNotNull(requireNotNull(db).monthlyArrangementCacheDao().read(key, "2026-09", "saved"))
                .copy(bindingKey = otherKey)
            requireNotNull(db).monthlyArrangementCacheDao().write(otherSaved)
            if (allLedgers) coordinator.clearLocalCache()
            else requireNotNull(db).expenseDao().clearAllExpenseCachesForLedger(original.ledgerId)
            assertEquals(if (allLedgers) null else otherSaved,
                requireNotNull(db).monthlyArrangementCacheDao().read(otherKey, "2026-09", "saved"))
            offline = true
            repository = reopen()
            assertTrue(repository.arrangement(original, "2026-09").isFailure)
            assertTrue(repository.arrangementHistory(original, "2026-09").isFailure)
            assertEquals(draftBefore, requireNotNull(db).monthlyArrangementCacheDao().read(key, "2026-09", "draft"))
            assertEquals(otherDraft, requireNotNull(db).monthlyArrangementCacheDao().read(otherKey, "2026-09", "draft"))
            assertEquals(before, requireNotNull(db).pendingMutationDao().allRows())
        }
    }
    @Test fun explicitCacheClearingPreventsAnEarlierGetFromRepublishing() = runBlocking {
        val original = binding()
        val repository = reopen()
        repository.arrangement(original, "2026-09").getOrThrow()
        val release = CompletableDeferred<Unit>()
        delayedRead = release
        val oldRead = async { repository.arrangement(original, "2026-09") }
        readStarted.await()
        coordinator.clearLocalCache()
        val stampsAtClear = snapshots.toMap()
        release.complete(Unit)
        assertTrue(oldRead.await().isFailure)
        assertEquals(stampsAtClear, snapshots)
        delayedRead = null
        offline = true
        assertTrue(reopen().arrangement(original, "2026-09").isFailure)
    }
    @Test fun confirmedSaveRetainsItsReceiptWithoutBlockingTheNextVersion() = runBlocking {
        loseAck = false
        val original = binding()
        var repository = reopen()
        val first = repository.enqueueArrangement(original, "2026-09",
            MonthlyArrangementSaveRequest("JPY", 1200, 300)).getOrThrow()
        assertEquals(1, drain().done)
        val accepted = repository.observeArrangements(original).first().single { it.row.id == first }
        assertTrue(accepted.isConfirmed)
        repository = reopen()
        val second = repository.enqueueArrangement(original, "2026-09",
            MonthlyArrangementSaveRequest("JPY", 1800, 300, 1)).getOrThrow()
        assertNotEquals(first, second)
        // The retained Done row permits a new version; its unresolved successor still blocks a third.
        assertTrue(repository.enqueueArrangement(original, "2026-09",
            MonthlyArrangementSaveRequest("JPY", 2000, 300, 1)).isFailure)
        assertEquals(1, drain().done)
        assertEquals(2L, fact?.rowVersion)
        assertEquals(1800L, fact?.savingsTargetCents)
        val rows = repository.observeArrangements(original).first()
        assertEquals(2, rows.size)
        assertTrue(rows.all { it.isConfirmed })
        assertEquals(accepted, rows.single { it.row.id == first })
        assertNotEquals(calls[0].second, calls[1].second)
        assertNull(calls[0].first.expectedRowVersion)
        assertEquals(1L, calls[1].first.expectedRowVersion)
        assertEquals(2, receipts.size)
    }
    @Test fun originalDraftSavedProjectionAndAckUnknownSurviveRoomReopenWithSameKey() = runBlocking {
        val original = binding()
        var repository = reopen()
        val draft = MonthlyArrangementDraft("JPY", "1200", "300", null, true)
        repository.storeArrangementDraft(original, "2026-09", draft)
        assertNull(repository.arrangement(original, "2026-09").getOrThrow().response.arrangement)
        val id = repository.enqueueArrangement(original, "2026-09", draft.request()).getOrThrow()
        assertEquals(0, calls.size)
        assertEquals(1, drain().retryable)
        val key = requireNotNull(db).pendingMutationDao().allRows().single().idempotencyKey
        clock = Clock.offset(clock, Duration.ofMinutes(2))
        repository = reopen()
        assertEquals(draft, repository.arrangementDraft(original, "2026-09"))
        assertEquals(key, requireNotNull(db).pendingMutationDao().allRows().single().idempotencyKey)
        assertEquals(1, drain().done)
        assertEquals(calls.first(), calls.last())
        assertEquals(1, receipts.size)
        val completed = repository.observeArrangements(original).first().single { it.row.id == id }
        assertTrue(completed.isConfirmed)
        // Last successful GET was unconfigured; delivered original receipt must win after offline reopen.
        offline = true
        repository = reopen()
        val cached = repository.arrangement(original, "2026-09").getOrThrow()
        assertTrue(cached.fromCache)
        assertEquals(1200L, cached.response.arrangement!!.savingsTargetCents)
        assertEquals("JPY", cached.response.arrangement!!.homeCurrencyCode)
        val other = session.value.copy(bindingRevision = "other", identity = session.value.identity.copy(ledgerId = "other"))
        session.value = other
        assertNull(repository.arrangementDraft(binding(), "2026-09"))
        assertTrue(repository.arrangement(binding(), "2026-09").isFailure)
        assertTrue(repository.observeArrangements(binding()).first().isEmpty())
        assertTrue(repository.arrangement(original, "2026-09").isFailure)
    }
    @Test fun occConflictCannotRewriteOriginalVersionOrCrossBinding() = runBlocking {
        val original = binding()
        var repository = reopen()
        conflict = true
        repository.enqueueArrangement(original, "2026-09", MonthlyArrangementSaveRequest("JPY", 1200, 300, 4)).getOrThrow()
        assertEquals(1, drain().conflicts)
        repository = reopen()
        val pending = repository.observeArrangements(original).first().single()
        assertFalse(pending.canRetry)
        assertTrue(repository.recoverArrangement(original, pending, false).isFailure)
        assertEquals(4L, requireNotNull(db).pendingMutationDao().allRows().single().expectedRowVersion)
        session.value = session.value.copy(bindingRevision = "other", identity = session.value.identity.copy(ledgerId = "other"))
        assertTrue(repository.recoverArrangement(original, pending, true).isFailure)
        assertEquals(1, requireNotNull(db).pendingMutationDao().allRows().size)
    }
}
private inline fun <reified T> arrangementProxy(crossinline answer: (String) -> Any?): T = Proxy.newProxyInstance(
    T::class.java.classLoader, arrayOf(T::class.java)) { _, method, _ -> answer(method.name) } as T
