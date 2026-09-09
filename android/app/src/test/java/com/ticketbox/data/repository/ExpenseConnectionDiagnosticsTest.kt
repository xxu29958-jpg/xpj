package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.CURRENT_TICKETBOX_API_VERSION
import com.ticketbox.data.remote.dto.AuthCheckDto
import com.ticketbox.data.remote.dto.CategoriesDto
import com.ticketbox.data.remote.dto.MonthlyStatsDto
import com.ticketbox.data.remote.dto.MonthsDto
import com.ticketbox.data.remote.dto.RuntimeCompatibilityDto
import com.ticketbox.data.remote.dto.RuntimeCurrencyCapabilityDto
import com.ticketbox.data.remote.dto.RuntimeProductCapabilitiesDto
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import kotlin.test.fail

class ExpenseConnectionDiagnosticsTest {
    @Test
    fun readableLedgerCannotHideAnIncompatibleSubmissionProtocol() = runTest {
        val fixture = DiagnosticsFixture(apiVersion = "different-protocol")

        val result = fixture.repository.runConnectionDiagnostics(requireNotNull(fixture.repository.captureDeferredLedgerBinding())).getOrThrow()

        assertFalse(result.isHealthy, "Successful reads do not qualify writes")
        assertEquals(1, fixture.compatibilityReads)
        assertTrue(result.checks.any { it.detail?.contains("版本") == true })
    }

    @Test
    fun canonicalConfigurationBlockExplainsWhoMustContinue() = runTest {
        for ((conclusion, responsible) in mapOf("owner_action_required" to "安装拥有者",
            "configuration_required" to "管理员", "server_upgrade_required" to "管理员")) {
            val fixture = DiagnosticsFixture(conclusion = conclusion)

            val result = fixture.repository.runConnectionDiagnostics(requireNotNull(fixture.repository.captureDeferredLedgerBinding())).getOrThrow()

            assertFalse(result.isHealthy, conclusion)
            assertTrue(result.checks.any { it.detail?.contains(responsible) == true }, conclusion)
        }
    }

    @Test
    fun compatibleViewerCanDiagnoseWithoutSendingAMutation() = runTest {
        val fixture = DiagnosticsFixture(role = "viewer")

        val result = fixture.repository.runConnectionDiagnostics(requireNotNull(fixture.repository.captureDeferredLedgerBinding())).getOrThrow()

        assertTrue(result.isHealthy)
        assertEquals(1, fixture.compatibilityReads)
        assertTrue(fixture.reads.contains("confirmed"))
    }

    @Test
    fun matchingVersionWithoutOriginalUploadSupportStillRequiresCompatibleBuilds() = runTest {
        val fixture = DiagnosticsFixture(receiptVersion = null)

        val result = fixture.repository.runConnectionDiagnostics(requireNotNull(fixture.repository.captureDeferredLedgerBinding())).getOrThrow()

        assertFalse(result.isHealthy)
        assertTrue(result.checks.any { it.detail?.contains("版本") == true })
    }

    @Test
    fun failedAuthenticationStopsDependentProbes() = runTest {
        val fixture = DiagnosticsFixture(authFailure = RepositoryException("绑定已失效，请重新连接。"))

        val result = fixture.repository.runConnectionDiagnostics(requireNotNull(fixture.repository.captureDeferredLedgerBinding())).getOrThrow()

        assertFalse(result.isHealthy)
        assertEquals(listOf("auth"), fixture.reads)
        assertEquals(0, fixture.compatibilityReads)
    }

    @Test
    fun cancellationStopsTheDiagnosisInsteadOfBecomingAnotherFailedProbe() = runTest {
        val fixture = DiagnosticsFixture(authFailure = CancellationException("leave diagnostics"))

        try {
            fixture.repository.runConnectionDiagnostics(requireNotNull(fixture.repository.captureDeferredLedgerBinding()))
            fail("Cancellation must propagate")
        } catch (_: CancellationException) {
            assertEquals(listOf("auth"), fixture.reads)
            assertEquals(0, fixture.compatibilityReads)
        }
    }
}

private class DiagnosticsFixture(
    apiVersion: String = CURRENT_TICKETBOX_API_VERSION,
    conclusion: String = "compatible",
    role: String = "owner",
    authFailure: Exception? = null,
    receiptVersion: Int? = 1,
) {
    val reads = mutableListOf<String>()
    var compatibilityReads = 0
    private val base = FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0)
    private val api = object : ApiService by base {
        override suspend fun checkAuth(): AuthCheckDto {
            reads += "auth"
            authFailure?.let { throw it }
            return AuthCheckDto(
                status = "ok", serverId = TEST_SERVER_ID, dataGeneration = TEST_DATA_GENERATION,
                accountPublicId = TEST_ACCOUNT_PUBLIC_ID, devicePublicId = TEST_DEVICE_PUBLIC_ID,
                accountName = "我", ledgerId = "owner", ledgerName = "我的小票夹",
                deviceName = "Pixel", role = role, scope = "app",
            )
        }

        override suspend fun runtimeCompatibility(): RuntimeCompatibilityDto {
            compatibilityReads += 1
            return RuntimeCompatibilityDto(
                apiVersion, conclusion,
                RuntimeProductCapabilitiesDto(RuntimeCurrencyCapabilityDto("1:1:CNY"), receiptVersion),
            )
        }

        override suspend fun serverSettings() = base.serverSettings().copy(ledgerId = "owner", role = role)
            .also { reads += "settings" }

        override suspend fun pendingExpenses() = emptyList<com.ticketbox.data.remote.dto.ExpenseDto>()
            .also { reads += "pending" }

        override suspend fun confirmedExpenses(query: Map<String, String>) = base.confirmedExpenses(query)
            .also { reads += "confirmed" }

        override suspend fun monthlyStats(month: String?, tag: String?, timezone: String?, homeCurrencyCode: String?) =
            MonthlyStatsDto(homeCurrencyCode = "CNY", month = "2026-09", totalAmountCents = 0, count = 0, byCategory = emptyList()).also { reads += "stats" }

        override suspend fun categories() = CategoriesDto(emptyList()).also { reads += "categories" }
        override suspend fun months(timezone: String?) = MonthsDto(emptyList()).also { reads += "months" }
        override suspend fun duplicates() = emptyList<com.ticketbox.data.remote.dto.ExpenseDto>()
            .also { reads += "duplicates" }
    }
    val repository = expenseRepositoryFixture(
        expenseDao = FakeExpenseDao(),
        binding = testServerSessionBinding(
            apiClient = object : ApiServiceFactory {
                override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = api
            },
            settingsStore = boundSettingsStore(role = role),
            tokenStore = TestSessionFixture().apply { saveToken("diagnostic-test-session") },
        ),
    )
}
