package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.PairingCodeResponseDto
import com.ticketbox.domain.model.AccountDevice
import com.ticketbox.ui.navigation.parsePairingQrLink
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class LedgerRepositoryPairingQrTest {
    @Test
    fun newDeviceQrCarriesTheRequestServerAndExistingOneTimeCode() = runTest {
        val api = StubApi().apply {
            pairingCodeResult = PairingCodeResponseDto("12345678", "家庭", "2026-10-03T12:00:00Z")
        }
        val repository = testLedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = LedgerFakeSettingsStore(),
            tokenStore = ledgerSessionFixture("family", "家庭", serverUrl = "https://family.example.com"),
            expenseDao = LedgerFakeDao(),
        )
        val code = repository.createDevicePairingCode().getOrThrow()
        val input = parsePairingQrLink(requireNotNull(code.connectionUrl))
        assertEquals("https://family.example.com", input?.serverUrl)
        assertEquals(code.pairingCode, input?.pairingCode)
        assertEquals(listOf("family"), api.pairingCodeTargets)
        assertNull(api.pairingCodeRequests.single().recoveryDevicePublicId)

        val recovery = AccountDevice("device", "旧手机", "android", null, null, null, false)
        val recoverCode = repository.createDevicePairingCode(recovery).getOrThrow()
        assertNull(recoverCode.connectionUrl)
        assertEquals("device", api.pairingCodeRequests.last().recoveryDevicePublicId)
    }
}
