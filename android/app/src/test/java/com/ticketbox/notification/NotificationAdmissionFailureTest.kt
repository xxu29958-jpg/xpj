package com.ticketbox.notification

import android.app.Application
import android.content.Context
import android.content.ContextWrapper
import android.content.SharedPreferences
import com.ticketbox.data.local.LocalSettingsStore
import com.ticketbox.data.local.TICKETBOX_SETTINGS_PREFERENCES
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.repository.FakeApiService
import com.ticketbox.data.repository.FakePendingMutationDao
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LedgerRequestGuard
import com.ticketbox.data.repository.NotificationCaptureRepository
import com.ticketbox.data.repository.OutboxRepository
import com.ticketbox.data.repository.SettingsActions
import com.ticketbox.data.repository.TestSessionFixture
import com.ticketbox.data.repository.testApiServiceProvider
import com.ticketbox.data.repository.toOutboxBinding
import com.ticketbox.domain.model.NotificationDraft
import com.ticketbox.domain.model.NotificationDraftSource
import com.ticketbox.domain.model.NotificationPreferences
import com.ticketbox.viewmodel.SettingsViewModel
import com.ticketbox.viewmodel.SettingsViewModelTest
import java.io.File
import java.util.UUID
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.coroutines.test.resetMain
import org.junit.After
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowLog
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
@RunWith(RobolectricTestRunner::class)
@Config(application = Application::class, sdk = [35])
class NotificationAdmissionFailureTest {
    private val dispatcher = StandardTestDispatcher()
    private val app get() = RuntimeEnvironment.getApplication()

    @Before fun setUp() { Dispatchers.setMain(dispatcher) }
    @After fun tearDown() { Dispatchers.resetMain() }

    @Test fun listenerAdmissionFailureReachesLiveSettingsAndDiskReadUntilExplicitAcknowledgement() = runTest(dispatcher) {
        val f = AdmissionFixture()
        val store = LocalSettingsStore(app)
        val vm = SettingsViewModel(f.actions, store)
        runCurrent()
        f.dao.beforeInsert = { error("private notification merchant 26.80") }
        acceptNotificationCapture(f.repository, store, f.capture, f.binding, "private-delivery")
        runCurrent()
        val failed = assertNotNull(vm.uiState.value.notificationCaptureFailure)
        assertFalse(failed.persistenceFailed)
        assertTrue(f.dao.rows.isEmpty())
        assertEquals(0, f.scheduled)
        val coldStore = reopenFromDisk()
        val coldVm = SettingsViewModel(f.actions, coldStore)
        runCurrent()
        assertEquals(failed, coldVm.uiState.value.notificationCaptureFailure)
        assertPrivateContentAbsent()

        vm.saveNotificationPreferences(NotificationPreferences(autoCaptureEnabled = true))
        f.dao.beforeInsert = null
        acceptNotificationCapture(f.repository, store, f.capture, f.binding, "other-delivery")
        acceptNotificationCapture(f.repository, store, f.capture, f.binding, "other-delivery")
        runCurrent()
        assertEquals(1, f.dao.rows.size)
        assertEquals(failed, vm.uiState.value.notificationCaptureFailure)
        vm.acknowledgeNotificationCaptureFailure(failed)
        assertNull(vm.uiState.value.notificationCaptureFailure)
        assertNull(reopenFromDisk().notificationCaptureFailure(f.scope))
    }

    @Test fun originalAuthorityAloneCanReadAndAcknowledgeFailureAfterSwitchOrSignOut() = runTest(dispatcher) {
        val f = AdmissionFixture()
        val store = LocalSettingsStore(app)
        val vm = SettingsViewModel(f.actions, store)
        store.recordNotificationCaptureFailure(f.scope)
        runCurrent()
        val failed = assertNotNull(vm.uiState.value.notificationCaptureFailure)
        val original = f.binding
        for (other in listOf(original.copy(ledgerId = "other-ledger"), original.copy(ownerKey = "other-owner"),
            original.copy(serverUrl = "https://other.example.com"))) {
            f.access.value = LedgerAccessContext(other, true)
            runCurrent()
            assertNull(vm.uiState.value.notificationCaptureFailure)
            vm.acknowledgeNotificationCaptureFailure(failed)
            assertEquals(failed, store.notificationCaptureFailure(f.scope))
        }
        store.saveNotificationPreferences(NotificationPreferences(autoCaptureEnabled = true))
        store.clearLedgerScopedRuntimeState()
        store.clear()
        val reopened = reopenFromDisk()
        assertFalse(reopened.notificationPreferences().autoCaptureEnabled)
        assertEquals(failed, reopened.notificationCaptureFailure(f.scope))
        f.access.value = LedgerAccessContext(original.copy(sessionGeneration = "renewed", bindingRevision = "renewed"), true)
        runCurrent()
        assertEquals(failed, vm.uiState.value.notificationCaptureFailure)
    }

    @Test fun acknowledgementOfOlderFailureCannotEraseNewerFailure() = runTest(dispatcher) {
        val f = AdmissionFixture()
        val store = LocalSettingsStore(app)
        val vm = SettingsViewModel(f.actions, store)
        store.recordNotificationCaptureFailure(f.scope)
        runCurrent()
        val old = assertNotNull(vm.uiState.value.notificationCaptureFailure)
        store.recordNotificationCaptureFailure(f.scope)
        vm.acknowledgeNotificationCaptureFailure(old)
        val latest = assertNotNull(vm.uiState.value.notificationCaptureFailure)
        assertNotEquals(old.token, latest.token)
        assertEquals(latest, reopenFromDisk().notificationCaptureFailure(f.scope))
    }

    @Test fun failedPreferenceCommitRemainsVisibleInProcessAndDiagnosticsContainNoCaptureContent() = runTest(dispatcher) {
        val f = AdmissionFixture()
        val context = FailingPreferenceContext(app)
        context.failCommits = true
        val store = LocalSettingsStore(context)
        val vm = SettingsViewModel(f.actions, store)
        f.dao.beforeInsert = { error("private notification merchant 26.80") }
        acceptNotificationCapture(f.repository, store, f.capture, f.binding, "private-delivery")
        runCurrent()
        assertTrue(assertNotNull(vm.uiState.value.notificationCaptureFailure).persistenceFailed)
        assertNull(LocalSettingsStore(app).notificationCaptureFailure(f.scope))
        val diagnostics = ShadowLog.getLogsForTag("TicketboxNetwork").joinToString { it.msg }
        assertTrue(diagnostics.contains("notification_capture_status_save_failed"))
        assertFalse(diagnostics.contains("private notification merchant"))
        assertFalse(diagnostics.contains("private-delivery"))
    }

    @Test fun failedAcknowledgementDoesNotClearReminderOrClaimPersistence() = runTest(dispatcher) {
        val f = AdmissionFixture()
        val context = FailingPreferenceContext(app)
        val store = LocalSettingsStore(context)
        val vm = SettingsViewModel(f.actions, store)
        store.recordNotificationCaptureFailure(f.scope)
        runCurrent()
        val saved = assertNotNull(vm.uiState.value.notificationCaptureFailure)
        context.failCommits = true
        vm.acknowledgeNotificationCaptureFailure(saved)
        assertTrue(assertNotNull(vm.uiState.value.notificationCaptureFailure).persistenceFailed)
        assertEquals(saved, reopenFromDisk().notificationCaptureFailure(f.scope))
        context.failCommits = false
        vm.acknowledgeNotificationCaptureFailure(saved)
        assertNull(vm.uiState.value.notificationCaptureFailure)
        assertNull(reopenFromDisk().notificationCaptureFailure(f.scope))
    }

    @Test fun rejectedBindingAndChangedDuplicateAreReportedWithoutReplacingOriginalOrCreatingNewTask() = runTest(dispatcher) {
        val f = AdmissionFixture()
        val store = LocalSettingsStore(app)
        acceptNotificationCapture(f.repository, store, f.capture, f.binding, "one-delivery")
        assertNull(store.notificationCaptureFailure(f.scope))
        val original = f.dao.rows.values.single()
        val changed = PaymentNotificationResult.Expense(f.capture.draft.copy(amountCents = 5000))
        acceptNotificationCapture(f.repository, store, changed, f.binding, "one-delivery")
        assertNotNull(store.notificationCaptureFailure(f.scope))
        val oldBinding = f.binding
        f.session.rebindAsDifferentAccountForFixture("other", "owner", "other ledger", "other device", "other-token")
        acceptNotificationCapture(f.repository, store, f.capture, oldBinding, "late-delivery")
        assertNull(store.notificationCaptureFailure(notificationCaptureFailureScope(f.binding)))
        assertEquals(listOf(original), f.dao.rows.values.toList())
        assertEquals(1, f.scheduled)
    }

    /** Read committed XML through a fresh preference name, bypassing Android's process preference cache. */
    private fun reopenFromDisk(): LocalSettingsStore {
        val coldName = "notification-cold-${UUID.randomUUID()}"
        val folder = File(app.applicationInfo.dataDir, "shared_prefs")
        File(folder, "$TICKETBOX_SETTINGS_PREFERENCES.xml").copyTo(File(folder, "$coldName.xml"))
        val coldContext = object : ContextWrapper(app) {
            override fun getApplicationContext(): Context = this
            override fun getSharedPreferences(name: String, mode: Int): SharedPreferences =
                app.getSharedPreferences(if (name == TICKETBOX_SETTINGS_PREFERENCES) coldName else name, mode)
        }
        return LocalSettingsStore(coldContext)
    }

    private fun assertPrivateContentAbsent() {
        val xml = File(app.applicationInfo.dataDir, "shared_prefs/$TICKETBOX_SETTINGS_PREFERENCES.xml").readText()
        for (privateValue in listOf("private notification merchant", "private-delivery", "amount", "synthetic-session", "api.example.com")) {
            assertFalse(xml.contains(privateValue), privateValue)
        }
    }
}

private class FailingPreferenceContext(base: Context) : ContextWrapper(base) {
    var failCommits = false
    override fun getApplicationContext(): Context = this
    override fun getSharedPreferences(name: String, mode: Int): SharedPreferences {
        val delegate = super.getSharedPreferences(name, mode)
        return object : SharedPreferences by delegate {
            override fun edit(): SharedPreferences.Editor {
                val editor = delegate.edit()
                return object : SharedPreferences.Editor by editor {
                    override fun commit(): Boolean = !failCommits && editor.commit()
                }
            }
        }
    }
}

private class AdmissionFixture {
    val session = TestSessionFixture().apply { saveToken("synthetic-session") }
    private val provider = testApiServiceProvider(object : ApiServiceFactory {
        override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = FakeApiService(mutableListOf(), 0)
    }, session)
    val binding get() = requireNotNull(LedgerRequestGuard(provider).captureLogicalBinding())
    val scope get() = notificationCaptureFailureScope(binding)
    val dao = FakePendingMutationDao()
    var scheduled = 0
    val repository = NotificationCaptureRepository(provider, OutboxRepository(dao, onRowsDeleted = {},
        bindingProvider = { provider.currentSession().toOutboxBinding() }, onEnqueued = { scheduled++ }))
    val capture = PaymentNotificationResult.Expense(NotificationDraft(NotificationDraftSource.WeChat,
        2680, "private notification merchant", "餐饮", "2026-10-27T08:00:00Z"))
    val access = MutableStateFlow<LedgerAccessContext?>(LedgerAccessContext(binding, true))
    val actions = object : SettingsActions by SettingsViewModelTest.FakeSettingsActions() {
        override fun currentAccess(): LedgerAccessContext? = access.value
        override fun observeAccess() = access
    }
}
