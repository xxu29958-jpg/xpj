package com.ticketbox.viewmodel

import com.ticketbox.data.remote.dto.MyDeviceDto
import com.ticketbox.data.remote.dto.MyDeviceListResponseDto
import com.ticketbox.data.remote.dto.PairingCodeResponseDto
import com.ticketbox.data.repository.LedgerFakeDao
import com.ticketbox.data.repository.LedgerFakeSettingsStore
import com.ticketbox.data.repository.LedgerFakeTokenStore
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.data.repository.LedgerStubApiFactory
import com.ticketbox.data.repository.StubApi
import com.ticketbox.domain.model.AccountDevice
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * issue #65 slice 6b — owner gating + mutate→refresh contract for the My Devices
 * VM. The device list/mutations are owner-only on the backend (slice 6a), so the
 * VM must refuse to even call the API when the bound session is not OWNER, and a
 * successful rename/revoke must re-list (so the row reflects the new state).
 * Drives a real [LedgerRepository] over the Ledger stub fixtures.
 *
 * [LedgerRepository.wrap] hops to a real `Dispatchers.IO`, so positive paths are
 * awaited via `uiState.first { terminal }` (runTest pumps the scheduler while the
 * body suspends) rather than `advanceUntilIdle()` — the latter returns before the
 * real IO thread posts the continuation back and would leak it past resetMain.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class MyDevicesViewModelTest {

    private val ledger = "L_family"

    private fun harness(api: StubApi, role: String = "owner"): MyDevicesViewModel {
        val store = LedgerFakeSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveActiveLedger(ledger, "家庭账本")
            capturedRole = role
        }
        val repository = LedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = LedgerFakeTokenStore().apply { saveToken("t") },
            expenseDao = LedgerFakeDao(),
        )
        return MyDevicesViewModel(repository)
    }

    private fun deviceDto(
        publicId: String,
        name: String = "设备",
        isCurrent: Boolean = false,
        revokedAt: String? = null,
    ) = MyDeviceDto(
        publicId = publicId,
        deviceName = name,
        platform = "android",
        lastSeenAt = "2026-06-20T00:00:00Z",
        createdAt = "2026-06-01T00:00:00Z",
        revokedAt = revokedAt,
        isCurrent = isCurrent,
    )

    private fun accountDevice(publicId: String, name: String = "设备") = AccountDevice(
        publicId = publicId,
        deviceName = name,
        platform = "android",
        lastSeenAt = null,
        createdAt = null,
        revokedAt = null,
        isCurrent = false,
    )

    @Test
    fun refreshLoadsDevicesFromRepository() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi().apply {
                devicesResult = MyDeviceListResponseDto(
                    listOf(deviceDto("d1", "本机", isCurrent = true), deviceDto("d2")),
                )
            }
            val vm = harness(api)

            vm.refresh(ledger)
            val state = vm.uiState.first { it.devices.isNotEmpty() }

            assertEquals(listOf("d1", "d2"), state.devices.map { it.publicId })
            assertTrue(state.devices.first().isCurrent)
            assertEquals(ledger, api.deviceListRequests.single())
            assertNull(state.message)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun renameAsOwnerCallsApiThenRefreshes() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi().apply {
                devicesResult = MyDeviceListResponseDto(listOf(deviceDto("d2", "新名字")))
                renameDeviceResult = deviceDto("d2", "新名字")
            }
            val vm = harness(api)

            vm.rename(accountDevice("d2", "旧名字"), "  新名字  ", ledger)
            // message is set LAST (after the re-list), so it is the settle signal.
            val state = vm.uiState.first { it.message != null }

            assertEquals(ledger to "d2", api.renameDeviceTargets.single())
            assertEquals("新名字", api.renameDeviceRequests.single().deviceName)
            assertEquals(ledger, api.deviceListRequests.single())
            assertEquals(listOf("新名字"), state.devices.map { it.deviceName })
            assertNull(state.busyDeviceId)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun renameAsNonOwnerIsNoOp() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi().apply { renameDeviceResult = deviceDto("d2", "新名字") }
            val vm = harness(api, role = "member")

            // non-owner short-circuits BEFORE launching: nothing to await.
            vm.rename(accountDevice("d2"), "新名字", ledger)

            assertTrue(api.renameDeviceTargets.isEmpty())
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun renameWithBlankNameSkipsApiAndMessages() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi().apply { renameDeviceResult = deviceDto("d2") }
            val vm = harness(api)

            // blank name is rejected synchronously, before launching.
            vm.rename(accountDevice("d2"), "   ", ledger)

            assertTrue(api.renameDeviceTargets.isEmpty())
            assertNotNull(vm.uiState.value.message)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun revokeAsOwnerCallsApiThenRefreshes() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi().apply {
                devicesResult = MyDeviceListResponseDto(
                    listOf(deviceDto("d2", "平板", revokedAt = "2026-06-23T00:00:00Z")),
                )
                revokeDeviceResult = deviceDto("d2", revokedAt = "2026-06-23T00:00:00Z")
            }
            val vm = harness(api)

            vm.revoke(accountDevice("d2", "平板"), ledger)
            val state = vm.uiState.first { it.message != null }

            assertEquals(ledger to "d2", api.revokeDeviceTargets.single())
            assertEquals(ledger, api.deviceListRequests.single())
            assertTrue(state.devices.single().isRevoked)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun revokeAsNonOwnerIsNoOp() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi().apply { revokeDeviceResult = deviceDto("d2") }
            val vm = harness(api, role = "viewer")

            vm.revoke(accountDevice("d2"), ledger)

            assertTrue(api.revokeDeviceTargets.isEmpty())
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun deleteAsOwnerCallsApiThenRefreshes() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi().apply {
                // After removal only the current device remains in the re-listed result.
                devicesResult = MyDeviceListResponseDto(listOf(deviceDto("d1", "本机", isCurrent = true)))
            }
            val vm = harness(api)

            vm.delete(accountDevice("d2", "旧平板"), ledger)
            // message is set LAST (after the re-list), so it is the settle signal.
            val state = vm.uiState.first { it.message != null }

            assertEquals(ledger to "d2", api.deleteDeviceTargets.single())
            assertEquals(ledger, api.deviceListRequests.single())
            assertEquals(listOf("d1"), state.devices.map { it.publicId })
            assertNull(state.busyDeviceId)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun deleteAsNonOwnerIsNoOp() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi()
            val vm = harness(api, role = "member")

            vm.delete(accountDevice("d2"), ledger)

            assertTrue(api.deleteDeviceTargets.isEmpty())
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun deleteFailureSurfacesMessageAndClearsBusy() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi().apply { deleteDeviceError = RuntimeException("boom") }
            val vm = harness(api)

            vm.delete(accountDevice("d2", "旧平板"), ledger)
            val state = vm.uiState.first { it.message != null }

            assertEquals(ledger to "d2", api.deleteDeviceTargets.single())
            assertNull(state.busyDeviceId)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun createPairingCodeFailureSurfacesMessageAndClearsBusy() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi().apply { pairingCodeError = RuntimeException("boom") }
            val vm = harness(api)

            vm.createPairingCode(ledger)
            val state = vm.uiState.first { it.message != null }

            assertEquals(ledger, api.pairingCodeTargets.single())
            assertNull(state.createdPairingCode)
            assertTrue(!state.pairingCreating)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun createPairingCodeSetsCodeThenDismissClears() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi().apply {
                pairingCodeResult = PairingCodeResponseDto(
                    pairingCode = "12345678",
                    ledgerName = "家庭账本",
                    expiresAt = "2026-06-23T01:00:00Z",
                )
            }
            val vm = harness(api)

            vm.createPairingCode(ledger)
            val state = vm.uiState.first { it.createdPairingCode != null }

            assertEquals(ledger, api.pairingCodeTargets.single())
            assertEquals("12345678", state.createdPairingCode?.pairingCode)

            vm.dismissPairingCode()
            assertNull(vm.uiState.value.createdPairingCode)
        } finally {
            Dispatchers.resetMain()
        }
    }
}
