package com.ticketbox.viewmodel

import com.ticketbox.data.remote.dto.InvitationAcceptResponseDto
import com.ticketbox.data.remote.dto.InvitationPreviewResponseDto
import com.ticketbox.data.repository.LedgerFakeDao
import com.ticketbox.data.repository.LedgerFakeSettingsStore
import com.ticketbox.data.repository.LedgerFakeTokenStore
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.data.repository.LedgerStubApiFactory
import com.ticketbox.data.repository.StubApi
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * Cold-start join contract: the server-URL override is pinned to the preview
 * the user is looking at — accept reuses exactly that URL, a URL edit drops
 * the preview (forcing a re-preview), and [JoinFamilyLedgerViewModel.reset]
 * returns an activity-retained instance to a fresh state. Drives a real
 * [LedgerRepository] over the Ledger stub fixtures so the pin is verified
 * end-to-end down to the persisted binding.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class JoinFamilyLedgerViewModelTest {

    private fun unboundHarness(api: StubApi): Triple<JoinFamilyLedgerViewModel, LedgerFakeSettingsStore, LedgerFakeTokenStore> {
        val store = LedgerFakeSettingsStore()
        val tokenStore = LedgerFakeTokenStore()
        val repository = LedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = tokenStore,
            expenseDao = LedgerFakeDao(),
        )
        return Triple(JoinFamilyLedgerViewModel(repository), store, tokenStore)
    }

    @Test
    fun previewThenAcceptRoutesAcceptThroughPreviewedServerUrl() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi(
                previewResult = InvitationPreviewResponseDto(
                    ledgerId = "L_family",
                    ledgerName = "家庭账本",
                    role = "member",
                    expiresAt = "2026-07-01T00:00:00Z",
                ),
                acceptResult = InvitationAcceptResponseDto(
                    sessionToken = "tk_joined",
                    accountName = "新成员",
                    ledgerId = "L_family",
                    ledgerName = "家庭账本",
                    deviceName = "Pixel 9",
                    role = "member",
                ),
            )
            val (viewModel, store, tokenStore) = unboundHarness(api)

            viewModel.previewInvitation("inv_VM", serverUrlOverride = "https://join.example.com")
            val previewed = viewModel.uiState.first { it.preview != null || it.error != null }
            assertNull(previewed.error)
            assertEquals("L_family", previewed.preview?.ledgerId)

            var accepted = false
            var consumed = false
            viewModel.acceptInvitation(
                inviteToken = "inv_VM",
                accountName = "新成员",
                deviceName = "Pixel 9",
                onAccepted = { accepted = true },
                onConsumed = { consumed = true },
            )
            val done = viewModel.uiState.first { it.success != null || it.error != null }

            // Mutation guard: if accept stopped forwarding the previewed
            // override, the unbound repository fails with "not bound" and
            // these all flip.
            assertNull(done.error)
            assertNotNull(done.success)
            assertTrue(accepted)
            assertTrue(consumed)
            assertEquals("https://join.example.com", store.serverUrl())
            assertEquals("tk_joined", tokenStore.getToken())
            assertEquals("inv_VM", api.acceptRequests.single().inviteToken)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun serverUrlEditAfterPreviewDropsPreviewAndBlocksAccept() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi(
                previewResult = InvitationPreviewResponseDto(
                    ledgerId = "L_family",
                    ledgerName = "家庭账本",
                    role = "member",
                    expiresAt = null,
                ),
            )
            val (viewModel, _, _) = unboundHarness(api)

            viewModel.previewInvitation("inv_VM", serverUrlOverride = "https://join.example.com")
            viewModel.uiState.first { it.preview != null || it.error != null }
            assertNotNull(viewModel.uiState.value.preview)

            // Editing the URL invalidates the preview; the previewed-URL /
            // preview pair can never diverge.
            viewModel.onServerUrlChanged()
            assertNull(viewModel.uiState.value.preview)

            viewModel.acceptInvitation(
                inviteToken = "inv_VM",
                accountName = "新成员",
                deviceName = "Pixel 9",
                onAccepted = {},
                onConsumed = {},
            )
            advanceUntilIdle()
            assertTrue(api.acceptRequests.isEmpty())
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun resetReturnsRetainedViewModelToFreshState() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi(
                previewResult = InvitationPreviewResponseDto(
                    ledgerId = "L_family",
                    ledgerName = "家庭账本",
                    role = "member",
                    expiresAt = null,
                ),
            )
            val (viewModel, _, _) = unboundHarness(api)

            viewModel.previewInvitation("inv_VM", serverUrlOverride = "https://join.example.com")
            viewModel.uiState.first { it.preview != null || it.error != null }

            viewModel.reset()

            assertEquals(JoinFamilyLedgerUiState(), viewModel.uiState.value)
            // The pinned override died with the preview: accept is a no-op
            // until a fresh preview succeeds.
            viewModel.acceptInvitation(
                inviteToken = "inv_VM",
                accountName = "新成员",
                deviceName = "Pixel 9",
                onAccepted = {},
                onConsumed = {},
            )
            advanceUntilIdle()
            assertTrue(api.acceptRequests.isEmpty())
        } finally {
            Dispatchers.resetMain()
        }
    }
}
