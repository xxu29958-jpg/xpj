package com.ticketbox.data.repository

import android.app.Application
import android.content.Context
import androidx.concurrent.futures.CallbackToFutureAdapter
import androidx.room.Room
import androidx.work.Configuration
import androidx.work.ListenableWorker
import androidx.work.WorkInfo
import androidx.work.WorkManager
import androidx.work.WorkerFactory
import androidx.work.WorkerParameters
import androidx.work.testing.SynchronousExecutor
import androidx.work.testing.TestDriver
import androidx.work.testing.WorkManagerTestInitHelper
import com.google.common.util.concurrent.ListenableFuture
import com.ticketbox.data.local.AppDatabase
import com.ticketbox.data.local.PendingMutationEntity
import com.ticketbox.data.local.PendingMutationType
import java.io.Closeable
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
import java.util.UUID
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.annotation.SQLiteMode

/** Real WorkManager queue and Room outbox; the factory controls only the final worker-result gap. */
@RunWith(RobolectricTestRunner::class)
@Config(application = Application::class, sdk = [35])
@SQLiteMode(SQLiteMode.Mode.NATIVE)
class OutboxSchedulerContinuationTest {
    @Test
    fun anEnqueueAfterTheFinalEmptyReadPersistsASuccessorWithoutCancellingTheRunningWorker() {
        SchedulerContinuationFixture().use { fixture ->
            val running = fixture.startAtFinalEmptyRead()
            val original = fixture.enqueueOriginal()

            val chain = fixture.workInfos()
            assertEquals("The persisted original requires a successor while the old worker is RUNNING", 2, chain.size)
            val successor = chain.single { it.id != running.id }
            assertEquals(WorkInfo.State.RUNNING, fixture.workInfo(running.id).state)
            assertFalse(requireNotNull(fixture.firstWorker).isStopped)
            assertEquals(WorkInfo.State.BLOCKED, successor.state)
            assertEquals(original, fixture.row())
            assertEquals(0, fixture.delivered.size)

            fixture.releaseFirstWorker()
            assertEquals(WorkInfo.State.SUCCEEDED, fixture.workInfo(running.id).state)
            assertEquals(WorkInfo.State.ENQUEUED, fixture.workInfo(successor.id).state)
            fixture.driver.setAllConstraintsMet(successor.id)

            assertEquals(WorkInfo.State.SUCCEEDED, fixture.workInfo(successor.id).state)
            fixture.assertOriginalDelivered(original)
        }
    }

    @Test
    fun anExplicitCancelDoesNotPreventTheNextOriginalFromStartingANewChain() {
        SchedulerContinuationFixture().use { fixture ->
            val running = fixture.startAtFinalEmptyRead()
            fixture.scheduler.cancel(fixture.context)
            assertEquals(WorkInfo.State.CANCELLED, fixture.workInfo(running.id).state)

            val original = fixture.enqueueOriginal()
            val replacement = fixture.workInfos().single()
            assertNotEquals(running.id, replacement.id)
            assertEquals(WorkInfo.State.ENQUEUED, replacement.state)
            fixture.driver.setAllConstraintsMet(replacement.id)

            assertEquals(WorkInfo.State.SUCCEEDED, fixture.workInfo(replacement.id).state)
            fixture.assertOriginalDelivered(original)
        }
    }
}

private class SchedulerContinuationFixture : Closeable {
    val context: Application = RuntimeEnvironment.getApplication()
    private val database = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java)
        .allowMainThreadQueries().build()
    private val clock = Clock.fixed(Instant.parse("2026-09-07T00:00:00Z"), ZoneOffset.UTC)
    private lateinit var manager: WorkManager
    val scheduler = OutboxScheduler { manager }
    private val outbox = testOutboxRepository(database.pendingMutationDao(), clock,
        onEnqueued = { scheduler.enqueueOnce(context) })
    val delivered = mutableListOf<OutboxRow>()
    private val dispatcher = object : OutboxMutationDispatcher {
        override val type = PendingMutationType.PatchExpense
        override suspend fun dispatch(row: OutboxRow): DispatchResult {
            delivered += row
            return DispatchResult.Success(newRowVersion = 8)
        }
    }
    private val engine = OutboxDrainEngine(outbox, listOf(dispatcher), now = clock::millis)
    private var firstSummary: DrainSummary? = null
    private var firstCompletion: CallbackToFutureAdapter.Completer<ListenableWorker.Result>? = null
    var firstWorker: ListenableWorker? = null
        private set
    val driver: TestDriver

    init {
        assertEquals("TicketboxApplication must never enter this JVM sandbox", Application::class.java, context.javaClass)
        val configuration = Configuration.Builder()
            .setExecutor(SynchronousExecutor())
            .setTaskExecutor(SynchronousExecutor())
            .setWorkerFactory(workerFactory())
            .build()
        WorkManagerTestInitHelper.initializeTestWorkManager(context, configuration)
        manager = WorkManager.getInstance(context)
        driver = requireNotNull(WorkManagerTestInitHelper.getTestDriver(context))
    }

    private fun workerFactory() = object : WorkerFactory() {
        override fun createWorker(context: Context, workerClassName: String, parameters: WorkerParameters): ListenableWorker {
            assertEquals(OutboxDrainWorker::class.java.name, workerClassName)
            return FinalResultWorker(context, parameters, ::runDrainBeforeCompleting).also {
                if (firstWorker == null) firstWorker = it
            }
        }
    }

    private fun runDrainBeforeCompleting(completion: CallbackToFutureAdapter.Completer<ListenableWorker.Result>) {
        var summary = DrainSummary.IDLE
        val outcome = runBlocking {
            OutboxDrainWorker.runDrain { engine.drainOnce().also { summary = it } }
        }
        assertEquals(OutboxDrainWorker.DrainOutcome.SUCCESS, outcome)
        if (firstCompletion == null) {
            firstSummary = summary
            firstCompletion = completion
        } else {
            completion.set(ListenableWorker.Result.success())
        }
    }

    fun startAtFinalEmptyRead(): WorkInfo {
        scheduler.enqueueOnce(context)
        val enqueued = workInfos().single()
        assertEquals(WorkInfo.State.ENQUEUED, enqueued.state)
        driver.setAllConstraintsMet(enqueued.id)
        assertEquals(DrainSummary.IDLE, firstSummary)
        return workInfo(enqueued.id).also { assertEquals(WorkInfo.State.RUNNING, it.state) }
    }

    fun enqueueOriginal(): PendingMutationEntity = runBlocking {
        outbox.enqueue(PendingMutationType.PatchExpense, "expense:7",
            """{"merchant":"Original queued after the empty read"}""", 7, UUID.randomUUID().toString())
        row()
    }

    fun row(): PendingMutationEntity = runBlocking { database.pendingMutationDao().allRows().single() }

    fun workInfos(): List<WorkInfo> = manager.getWorkInfosForUniqueWork(OutboxScheduler.ONE_TIME_WORK_NAME)
        .get(10, TimeUnit.SECONDS)

    fun workInfo(id: UUID): WorkInfo = requireNotNull(manager.getWorkInfoById(id).get(10, TimeUnit.SECONDS))

    fun releaseFirstWorker() {
        firstCompletion?.set(ListenableWorker.Result.success())
    }

    fun assertOriginalDelivered(original: PendingMutationEntity) {
        val stored = row()
        val sent = delivered.single()
        assertEquals("done", stored.status)
        assertEquals(original.id, sent.id)
        assertEquals(original.payload, sent.payloadJson)
        assertEquals(original.idempotencyKey, sent.idempotencyKey)
        assertEquals(original.expectedRowVersion, sent.expectedRowVersion)
        assertEquals(original.payload, stored.payload)
        assertEquals(original.idempotencyKey, stored.idempotencyKey)
        assertEquals(original.expectedRowVersion, stored.expectedRowVersion)
    }

    override fun close() {
        releaseFirstWorker()
        try {
            // Both WorkManager executors are synchronous and every controlled result is now settled.
            manager.cancelAllWork().result.get(10, TimeUnit.SECONDS)
            WorkManagerTestInitHelper.closeWorkDatabase()
        } finally {
            database.close()
        }
    }
}

private class FinalResultWorker(
    context: Context,
    parameters: WorkerParameters,
    private val drain: (CallbackToFutureAdapter.Completer<Result>) -> Unit,
) : ListenableWorker(context, parameters) {
    override fun startWork(): ListenableFuture<Result> = CallbackToFutureAdapter.getFuture { completion ->
        drain(completion)
        "outbox-drain-final-result"
    }
}
