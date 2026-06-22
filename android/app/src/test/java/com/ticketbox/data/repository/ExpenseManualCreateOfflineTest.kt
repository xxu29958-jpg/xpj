package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.domain.model.ExpenseSourceValues
import kotlinx.coroutines.test.runTest
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * issue #65 slice 4: offline-aware manual create end-to-end at the repository
 * layer. Covers the four Slice 4 acceptance lines that are testable without an
 * emulator: airplane-mode create shows immediately as a pending row, online
 * create stays direct, a create-response-loss lets a later edit address the row
 * via ``local:{client_ref}``, and a synced create replaces the temp local
 * identity with the server identity.
 */
internal class ExpenseManualCreateOfflineTest : ExpensePendingRepositoryOutboxTestBase() {

    private val activeLedger = "family"

    private class ManualCreateApi(
        private val dto: ExpenseDto? = null,
        private val failure: Throwable? = null,
    ) : ApiService by FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0) {
        var lastRequest: ExpenseManualCreateRequestDto? = null
            private set

        override suspend fun createManualExpense(request: ExpenseManualCreateRequestDto): ExpenseDto {
            lastRequest = request
            failure?.let { throw it }
            return requireNotNull(dto) { "ManualCreateApi needs a dto or a failure" }
        }
    }

    private fun confirmedDto(id: Long = 42L, rowVersion: Long = 1L): ExpenseDto =
        successExpenseDto().copy(id = id, status = "confirmed", rowVersion = rowVersion, publicId = "server-pub-$id")

    private fun createRepo(api: ApiService, dao: FakeExpenseDao, outbox: OutboxRepository): ExpenseRepository =
        ExpenseRepository(
            expenseDao = dao,
            apiClient = TestApiServiceFactory(api),
            settingsStore = seededSettingsStore(),
            tokenStore = seededTokenStore(),
            deviceNameProvider = { "Android Test" },
            outbox = outbox,
            patchExpenseAdapter = moshi().adapter(ExpenseUpdateRequest::class.java),
            manualCreateAdapter = moshi().adapter(ExpenseManualCreateRequestDto::class.java),
        )

    @Test
    fun `offline create writes a pending local row and queues CreateExpense`() = runTest {
        val dao = FakeExpenseDao()
        val pendingDao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = pendingDao)
        val api = ManualCreateApi(failure = IOException("airplane mode"))
        val repo = createRepo(api, dao, outbox)

        val expense = repo.createManualExpense(draft).getOrThrow()

        // Optimistic projection surfaced to the UI immediately.
        assertTrue(expense.pendingSync, "an offline create must be pendingSync")
        assertTrue(expense.id < 0, "a not-yet-synced row carries a negative local id: ${expense.id}")
        assertNotNull(expense.clientRef, "the optimistic expense must carry its client_ref")

        // The local row is cached as a confirmed manual entry (shows in the ledger list).
        val cached = dao.getConfirmed(activeLedger).single()
        assertNull(cached.serverId, "no server id until the CreateExpense row syncs")
        assertEquals(expense.clientRef, cached.clientRef)
        assertEquals(ExpenseSourceValues.MANUAL_ENTRY, cached.source)

        // Exactly one CreateExpense outbox row, addressed by the local ref, no prior version.
        val row = pendingDao.rows.values.single()
        assertEquals(PendingMutationType.CreateExpense.wireValue, row.type)
        assertEquals("expense:local:${expense.clientRef}", row.targetId)
        assertEquals(0L, row.expectedRowVersion)
        assertEquals(PendingMutationStatus.Pending.wireValue, row.status)
        assertTrue("\"client_ref\"" in row.payload, "payload must carry client_ref: ${row.payload}")
        assertNull(row.idempotencyKey, "create idempotency is the body client_ref, not a header key")
    }

    @Test
    fun `online create stays direct, sends client_ref, enqueues nothing`() = runTest {
        val dao = FakeExpenseDao()
        val pendingDao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = pendingDao)
        val api = ManualCreateApi(dto = confirmedDto(id = 42L))
        val repo = createRepo(api, dao, outbox)

        val expense = repo.createManualExpense(draft).getOrThrow()

        assertEquals(42L, expense.id)
        assertFalse(expense.pendingSync, "a server-confirmed create is not pendingSync")
        assertNotNull(api.lastRequest?.clientRef, "the direct attempt must still send a client_ref (lost-response dedup)")
        assertEquals(0, pendingDao.rows.size, "a successful online create enqueues nothing")
        assertEquals(42L, dao.getConfirmed(activeLedger).single().serverId, "the confirmed server row is cached")
    }

    @Test
    fun `a later edit of a create-response-lost row addresses it by local ref`() = runTest {
        val dao = FakeExpenseDao()
        val pendingDao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = pendingDao)
        // Create offline → local row + queued CreateExpense (response lost / airplane mode).
        val repo = createRepo(ManualCreateApi(failure = IOException("airplane mode")), dao, outbox)
        val pending = repo.createManualExpense(draft).getOrThrow()

        // Edit the not-yet-synced row. The unresolved CreateExpense for the same
        // local target makes the FIFO guard divert this to the queue, and it MUST
        // address the row by its local ref (the negative id can't be resolved).
        val outcome = repo.saveExpenseAllowingOffline(pending.id, draft, baseline = pending)
            .getOrThrow() as SaveOutcome.Queued

        assertEquals("新商家", outcome.expense.merchant)
        val patchRow = pendingDao.rows.values.single { it.type == PendingMutationType.PatchExpense.wireValue }
        assertEquals(
            "expense:local:${pending.clientRef}",
            patchRow.targetId,
            "a later edit of a pending create must replay against the local ref",
        )
    }

    @Test
    fun `syncing a create replaces the temp local identity with the server identity`() = runTest {
        val dao = FakeExpenseDao()
        val clientRef = "abc-123"
        // Seed the optimistic local row as the offline create would have.
        dao.insert(draft.toLocalCreateEntity(activeLedger, clientRef))
        assertNull(dao.getConfirmed(activeLedger).single().serverId, "precondition: row has no server id")

        // Dispatch the CreateExpense replay with the write-back wired exactly as
        // AppContainer wires it (DAO.applyLocalCreateServerIdentity).
        val api = ManualCreateApi(dto = confirmedDto(id = 77L, rowVersion = 3L))
        val dispatcher = CreateExpenseDispatcher(
            apiProvider = { api },
            payloadAdapter = moshi().adapter(ExpenseManualCreateRequestDto::class.java),
            applyServerIdentity = { ledgerId, ref, created ->
                dao.applyLocalCreateServerIdentity(ledgerId, created.toEntity(ledgerId).copy(clientRef = ref))
            },
        )
        val payload = moshi().adapter(ExpenseManualCreateRequestDto::class.java)
            .toJson(draft.toManualCreateRequest(clientRef = clientRef))
        val row = OutboxRow(
            id = 1L,
            serverUrl = "https://api.example.com",
            ledgerId = activeLedger,
            type = PendingMutationType.CreateExpense,
            targetId = "expense:local:$clientRef",
            payloadJson = payload,
            expectedRowVersion = 0L,
            status = PendingMutationStatus.InFlight,
            retryCount = 0,
            lastError = null,
            createdAt = "2026-05-20T12:00:00.000Z",
            attemptedAt = "2026-05-20T12:00:00.000Z",
            completedAt = null,
            idempotencyKey = null,
        )

        val result = dispatcher.dispatch(row)

        assertEquals(DispatchResult.Success(newRowVersion = 3L), result)
        val synced = dao.getConfirmed(activeLedger).single()
        assertEquals(77L, synced.serverId, "the temp local row is promoted to the server id")
        assertEquals(3L, synced.rowVersion)
        assertEquals("server-pub-77", synced.publicId)
        assertEquals(77L, synced.toDomain().id, "domain id flips from negative local to positive server id")
        assertFalse(synced.toDomain().pendingSync, "the row is no longer pending after sync")
    }
}
