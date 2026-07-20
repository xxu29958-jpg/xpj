package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.remote.dto.MyDeviceDto
import com.ticketbox.data.remote.dto.MyDeviceListResponseDto
import com.ticketbox.data.remote.dto.PairingCodeResponseDto
import com.ticketbox.data.repository.LedgerFakeDao
import com.ticketbox.data.repository.LedgerFakeSettingsStore
import com.ticketbox.data.repository.ledgerSessionFixture
import com.ticketbox.data.repository.testLedgerRepository
import com.ticketbox.data.repository.LedgerStubApiFactory
import com.ticketbox.data.repository.StubApi
import com.ticketbox.domain.model.AccountDevice
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
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
 * Account-scoped device lifecycle and mutate→refresh contract. Ledger role must
 * not block a member from managing their own Account's devices.
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
        val repository = testLedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = ledgerSessionFixture(ledger, "家庭账本", role = role, token = "t"),
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
    fun initialRefreshFailureShowsDangerLoadMessage() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi().apply { devicesError = RuntimeException() }
            val vm = harness(api)

            vm.refresh(ledger)
            val state = vm.uiState.first { !it.loading && it.message != null }

            assertTrue(state.devices.isEmpty())
            assertEquals(UiText.res(R.string.my_devices_message_load_failed), state.message)
            assertEquals(MessageTone.Danger, state.messageTone)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun refreshFailureAfterLoadedDevicesKeepsRowsAndShowsStaleMessage() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi().apply {
                devicesResult = MyDeviceListResponseDto(listOf(deviceDto("d1", "本机", isCurrent = true)))
            }
            val vm = harness(api)
            vm.refresh(ledger)
            vm.uiState.first { !it.loading && it.devices.isNotEmpty() }
            api.devicesError = RuntimeException()

            vm.refresh(ledger)
            val state = vm.uiState.first { !it.loading && it.message != null }

            assertEquals(listOf("d1"), state.devices.map { it.publicId })
            assertEquals(UiText.res(R.string.my_devices_message_refresh_failed_with_data), state.message)
            assertEquals(MessageTone.Danger, state.messageTone)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun mutationSuccessWithRefreshFailureKeepsRowsAndShowsStaleMessage() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi().apply {
                devicesResult = MyDeviceListResponseDto(listOf(deviceDto("d2", "旧名字")))
                renameDeviceResult = deviceDto("d2", "新名字")
            }
            val vm = harness(api)
            vm.refresh(ledger)
            vm.uiState.first { !it.loading && it.devices.isNotEmpty() }
            api.devicesError = RuntimeException()

            vm.rename(accountDevice("d2", "旧名字"), "新名字", ledger)
            val state = vm.uiState.first { it.message != null }

            assertEquals(listOf("旧名字"), state.devices.map { it.deviceName })
            assertEquals(UiText.res(R.string.my_devices_message_refresh_failed_with_data), state.message)
            assertEquals(MessageTone.Danger, state.messageTone)
            assertNull(state.busyDeviceId)
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
    fun memberCanRenameOwnDevice() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi().apply {
                renameDeviceResult = deviceDto("d2", "新名字")
                devicesResult = MyDeviceListResponseDto(listOf(deviceDto("d2", "新名字")))
            }
            val vm = harness(api, role = "member")

            vm.rename(accountDevice("d2"), "新名字", ledger)
            vm.uiState.first { it.message != null }

            assertEquals(ledger to "d2", api.renameDeviceTargets.single())
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
    fun viewerCanRevokeOwnDevice() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi().apply {
                revokeDeviceResult = deviceDto("d2", revokedAt = "2026-06-23T00:00:00Z")
                devicesResult = MyDeviceListResponseDto(
                    listOf(deviceDto("d2", revokedAt = "2026-06-23T00:00:00Z")),
                )
            }
            val vm = harness(api, role = "viewer")

            vm.revoke(accountDevice("d2"), ledger)
            vm.uiState.first { it.message != null }

            assertEquals(ledger to "d2", api.revokeDeviceTargets.single())
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
    fun memberCanDeleteRevokedOwnDevice() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi().apply {
                devicesResult = MyDeviceListResponseDto(emptyList())
            }
            val vm = harness(api, role = "member")

            vm.delete(accountDevice("d2"), ledger)
            vm.uiState.first { it.message != null }

            assertEquals(ledger to "d2", api.deleteDeviceTargets.single())
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
    fun recoverCreatesCodeForTheSelectedDeviceIdentity() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi().apply {
                pairingCodeResult = PairingCodeResponseDto(
                    pairingCode = "87654321",
                    ledgerName = "家庭账本",
                    expiresAt = "2026-06-23T01:00:00Z",
                )
            }
            val vm = harness(api, role = "member")

            vm.recover(accountDevice("d2", "旧手机"), ledger)
            val state = vm.uiState.first { it.createdPairingCode != null }

            assertEquals("d2", api.pairingCodeRequests.single().recoveryDevicePublicId)
            assertEquals("旧手机", state.createdPairingCode?.recoveryDeviceName)
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
            assertNull(api.pairingCodeRequests.single().recoveryDevicePublicId)
            assertEquals("12345678", state.createdPairingCode?.pairingCode)

            vm.dismissPairingCode()
            assertNull(vm.uiState.value.createdPairingCode)
        } finally {
            Dispatchers.resetMain()
        }
    }
}
