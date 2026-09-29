package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.BackgroundTaskDto
import com.ticketbox.data.remote.dto.BackgroundTaskListResponseDto
import com.ticketbox.viewmodel.BackgroundTasksViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response
import java.util.concurrent.atomic.AtomicInteger
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** Exercise the production repository/error mapping and task consumer together. */
@OptIn(ExperimentalCoroutinesApi::class)
class BackgroundTaskAccessRecoveryTest {
    private val dispatcher = StandardTestDispatcher()

    @BeforeTest
    fun setup() = Dispatchers.setMain(dispatcher)

    @AfterTest
    fun tearDown() = Dispatchers.resetMain()

    @Test
    fun removedLedgerMembershipWithdrawsReadRowsAndCanRecoverWithoutReplacingIdentity() =
        verifyReadDenial(403)

    @Test
    fun revokedDeviceWithdrawsReadRowsAndOriginalNavigation() = verifyReadDenial(401)

    private fun verifyReadDenial(status: Int) = runTest(dispatcher) {
        val responseStatus = AtomicInteger(200)
        val fxStarted = CompletableDeferred<Unit>()
        val fxReply = CompletableDeferred<BackgroundTaskDto>()
        val task = BackgroundTaskDto("original-upload", "expense_enrichment", "completed",
            createdAt = "2026-09-29T00:00:00Z", sourceExpenseId = 9L)
        fun response(): BackgroundTaskDto {
            val current = responseStatus.get()
            if (current != 200) throw HttpException(Response.error<Any>(current,
                """{"error":"forbidden","message":"当前账号无法读取该账本。"}""".toResponseBody()))
            return task
        }
        val api = object : ApiService by FakeApiService(mutableListOf(), 0) {
            override suspend fun listBackgroundTasks() = BackgroundTaskListResponseDto(items = listOf(response()))
            override suspend fun getBackgroundTask(publicId: String) = response()
            override suspend fun expenseFx(id: Long): BackgroundTaskDto {
                fxStarted.complete(Unit)
                return fxReply.await()
            }
        }
        val sessions = TestSessionFixture().apply { saveToken("isolated-session-token") }
        val factory = object : ApiServiceFactory {
            override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = api
        }
        val serverBinding = testServerSessionBinding(apiClient = factory,
            settingsStore = boundSettingsStore(), tokenStore = sessions)
        val dao = FakeExpenseDao()
        val coordinator = LocalLedgerSessionCoordinator(serverBinding.settingsStore, serverBinding.sessionStore, dao)
        val repository = expenseRepositoryFixture(dao, serverBinding, coordinator, deviceNameProvider = { "Test" })
        val originalSession = serverBinding.sessionStore.currentSession()
        val vm = BackgroundTasksViewModel(ExpenseRepositoryBackgroundTaskActions(repository))

        vm.refresh()
        vm.uiState.first { !it.loading && it.tasks.isNotEmpty() }
        assertEquals(9L, vm.sourceExpenseId(task.publicId))
        val binding = requireNotNull(repository.captureDeferredLedgerBinding())
        val oldFxRead = async { repository.fetchExpenseFx(binding, 9) }
        fxStarted.await()

        responseStatus.set(status)
        if (status == 403) {
            assertTrue(repository.pendingEnrichmentTasks.fetchPendingEnrichmentTask(task.publicId, binding).isFailure)
        } else vm.refresh()
        val denied = vm.uiState.first { !it.loading && it.message != null }
        assertTrue(denied.tasks.isEmpty(), "A denied task query still exposes its previous rows")
        assertNull(vm.sourceExpenseId(task.publicId))
        assertEquals(originalSession, serverBinding.sessionStore.currentSession())
        assertEquals(status, coordinator.snapshotAccessDenials.value?.failure?.httpStatusCode,
            "Other readers did not receive the existing session read-access refusal")
        fxReply.complete(task.copy(taskType = "expense_fx"))
        assertEquals(status, (oldFxRead.await().exceptionOrNull() as? RepositoryException)?.httpStatusCode,
            "A response started before the refusal republished stale task data")

        if (status == 401) return@runTest

        responseStatus.set(200)
        vm.refresh()
        val recovered = vm.uiState.first { !it.loading }
        assertEquals(listOf(task.publicId), recovered.tasks.map { it.publicId })
        assertEquals(9L, vm.sourceExpenseId(task.publicId))
        assertEquals(originalSession, serverBinding.sessionStore.currentSession())
        assertNull(coordinator.snapshotAccessDenials.value)
    }
}
