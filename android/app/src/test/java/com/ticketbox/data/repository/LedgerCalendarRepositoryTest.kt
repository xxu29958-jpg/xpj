package com.ticketbox.data.repository

import android.app.Application
import android.content.Context
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.LedgerCalendarDto
import com.ticketbox.security.SessionCredentialAdapter
import java.io.IOException
import kotlinx.coroutines.test.runTest
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

@RunWith(RobolectricTestRunner::class)
@Config(application = Application::class, sdk = [35])
class LedgerCalendarRepositoryTest {
    @Test fun ruleSurvivesReopenAndOfflineWithoutCrossingLogicalBindings() = runTest {
        val session = TestSessionFixture().apply { saveToken("synthetic-session") }
        val fallback = FakeApiService(mutableListOf(), 0)
        var offline = false
        var currentRevision = 2L
        val api = object : ApiService by fallback {
            override suspend fun runtimeCompatibility() = fallback.runtimeCompatibility().let {
                if (offline) throw IOException("offline")
                it.copy(capabilities = it.capabilities.copy(accountingTimeInputVersion = 1))
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
        assertTrue(reopened.refresh(binding).isFailure)
        assertEquals(3L, reopened.cached(binding)?.revision)
        assertEquals(2L, reopened.cached(binding, 2)?.revision)
        for (other in listOf(binding.copy(ledgerId = "other"), binding.copy(ownerKey = "other"),
            binding.copy(sessionGeneration = "other"), binding.copy(bindingRevision = "other"))) {
            assertNull(reopened.cached(other))
            assertTrue(reopened.refresh(other).isFailure)
        }
    }
}
