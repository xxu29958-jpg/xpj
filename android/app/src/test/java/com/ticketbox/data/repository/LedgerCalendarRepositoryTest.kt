package com.ticketbox.data.repository

import android.app.Application
import android.content.Context
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.LedgerCalendarDto
import com.ticketbox.security.SessionCredentialAdapter
import java.io.IOException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.async
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowLog
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertSame
import kotlin.test.assertTrue

@RunWith(RobolectricTestRunner::class)
@Config(application = Application::class, sdk = [35])
class LedgerCalendarRepositoryTest {
    @OptIn(ExperimentalCoroutinesApi::class)
    @Test fun overlappingReadsCannotRestoreAnOlderCurrentRuleOrAnUnsupportedCalendar() = runTest {
        for (unsupported in listOf(false, true)) {
            val session = TestSessionFixture().apply { saveToken("synthetic-session") }
            val fallback = FakeApiService(mutableListOf(), 0)
            val firstResponse = CompletableDeferred<Unit>()
            var compatibilityReads = 0
            var ruleReads = 0
            val api = object : ApiService by fallback {
                override suspend fun runtimeCompatibility() = fallback.runtimeCompatibility().let {
                    compatibilityReads += 1
                    it.copy(capabilities = it.capabilities.copy(
                        accountingTimeInputVersion = if (unsupported && compatibilityReads > 1) null else 1))
                }
                override suspend fun ledgerCalendar(ledgerId: String, revision: Long?): LedgerCalendarDto {
                    val capturedRevision = ++ruleReads
                    if (capturedRevision == 1) firstResponse.await()
                    return LedgerCalendarDto(ledgerId, capturedRevision.toLong(),
                        if (capturedRevision == 1) "Asia/Shanghai" else "America/Los_Angeles",
                        "explicit", "2026-09-20T00:00:00Z")
                }
            }
            val provider = ApiServiceProvider(object : ApiServiceFactory {
                override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = api
            }, session.sessionStore, SessionCredentialAdapter(session.sessionStore))
            val prefs = RuntimeEnvironment.getApplication().getSharedPreferences("calendar-overlap", Context.MODE_PRIVATE)
            prefs.edit().clear().commit()
            val repository = LedgerCalendarRepository(LedgerRequestGuard(provider), prefs)
            val binding = requireNotNull(repository.currentBinding())
            val old = async { repository.refresh(binding) }
            runCurrent()
            val newer = async { repository.refresh(binding) }
            runCurrent()
            firstResponse.complete(Unit)
            assertTrue(old.await().isSuccess)
            assertTrue(newer.await().isSuccess)
            assertEquals(if (unsupported) null else 2L, repository.cached(binding)?.revision)
            assertEquals(1L, repository.cached(binding, 1)?.revision)
            if (!unsupported) assertEquals("America/Los_Angeles", repository.cached(binding)?.timezoneName)
        }
    }

    @Test fun ruleSurvivesReopenAndOfflineWithoutCrossingLogicalBindings() = runTest {
        val session = TestSessionFixture().apply { saveToken("synthetic-session") }
        val fallback = FakeApiService(mutableListOf(), 0)
        var offline = false
        var supported = true
        var currentRevision = 2L
        val unavailable = IOException("synthetic private calendar response")
        val api = object : ApiService by fallback {
            override suspend fun runtimeCompatibility() = fallback.runtimeCompatibility().let {
                if (offline) throw unavailable
                it.copy(capabilities = it.capabilities.copy(accountingTimeInputVersion = if (supported) 1 else null))
            }
            override suspend fun ledgerCalendar(ledgerId: String, revision: Long?) =
                LedgerCalendarDto(ledgerId, revision ?: currentRevision, "Asia/Shanghai", "explicit", "2026-09-20T00:00:00Z")
        }
        val provider = ApiServiceProvider(object : ApiServiceFactory {
            override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = api
        }, session.sessionStore, SessionCredentialAdapter(session.sessionStore))
        val guard = LedgerRequestGuard(provider)
        val prefs = RuntimeEnvironment.getApplication().getSharedPreferences("calendar-test", Context.MODE_PRIVATE)
        prefs.edit().clear().commit()
        val repository = LedgerCalendarRepository(guard, prefs)
        val binding = requireNotNull(repository.currentBinding())
        assertTrue(repository.refresh(binding).isSuccess)
        currentRevision = 3
        assertTrue(repository.refresh(binding).isSuccess)
        val reopened = LedgerCalendarRepository(guard, prefs)
        offline = true
        ShadowLog.clear()
        assertSame(unavailable, reopened.refresh(binding).exceptionOrNull())
        val diagnostic = ShadowLog.getLogsForTag("TicketboxNetwork").single().msg
        assertTrue(diagnostic.contains("Ledger calendar refresh failed"))
        assertTrue(diagnostic.contains("IOException"))
        assertFalse(diagnostic.contains("synthetic private calendar response"))
        assertEquals(3L, reopened.cached(binding)?.revision)
        assertEquals(2L, reopened.cached(binding, 2)?.revision)
        for (other in listOf(binding.copy(ledgerId = "other"), binding.copy(ownerKey = "other"),
            binding.copy(sessionGeneration = "other"), binding.copy(bindingRevision = "other"))) {
            assertNull(reopened.cached(other))
            assertTrue(reopened.refresh(other).isFailure)
        }
        offline = false
        supported = false
        assertNull(reopened.refresh(binding).getOrThrow())
        assertNull(reopened.cached(binding))
        assertEquals(2L, reopened.cached(binding, 2)?.revision)
        offline = true
        val unsupportedReopened = LedgerCalendarRepository(guard, prefs)
        assertTrue(unsupportedReopened.refreshedLedgerDate(binding).isFailure)
        assertNull(unsupportedReopened.cached(binding))
    }
}
