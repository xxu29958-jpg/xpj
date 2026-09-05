package com.ticketbox.viewmodel

import com.ticketbox.data.remote.dto.InvitationAcceptResponseDto
import com.ticketbox.data.remote.dto.InvitationPreviewResponseDto
import com.ticketbox.data.repository.LedgerFakeDao
import com.ticketbox.data.repository.LedgerFakeSettingsStore
import com.ticketbox.data.repository.LedgerFakeTokenStore
import com.ticketbox.data.repository.LedgerStubApiFactory
import com.ticketbox.data.repository.LedgerStubApiState
import com.ticketbox.data.repository.StubApi
import com.ticketbox.data.repository.TEST_ACCOUNT_PUBLIC_ID
import com.ticketbox.data.repository.TEST_DATA_GENERATION
import com.ticketbox.data.repository.TEST_DEVICE_PUBLIC_ID
import com.ticketbox.data.repository.TEST_SERVER_ID
import com.ticketbox.data.repository.existingOwnerSessionFixture
import com.ticketbox.data.repository.testLedgerRepository
import com.ticketbox.domain.model.InvitationSessionTarget
import com.ticketbox.domain.model.FamilyInvitationCreated
import com.ticketbox.domain.model.shareText
import com.ticketbox.ui.navigation.LaunchIntentActions
import com.ticketbox.ui.navigation.LaunchIntentRequest
import com.ticketbox.ui.navigation.resolveLaunchIntent
import java.io.IOException
import kotlinx.coroutines.CompletableDeferred
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
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class JoinFamilyLedgerViewModelTest {

    @Test
    fun rawShareFallbackResolvesLaunchAndBoundSessionPreviewsCurrentServer() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = invitationApi()
            val factory = LedgerStubApiFactory(api)
            val repository = testLedgerRepository(
                apiClient = factory,
                settingsStore = LedgerFakeSettingsStore(),
                tokenStore = ownerSession(),
                expenseDao = LedgerFakeDao(),
            )
            val created = FamilyInvitationCreated(
                inviteToken = "inv_RAW_FALLBACK",
                inviteUrl = null,
                role = "member",
                expiresAt = null,
            )
            val request = resolveLaunchIntent(
                action = LaunchIntentActions.ACTION_SEND,
                mimeType = "text/plain",
                streamUris = emptyList(),
                shortcutTarget = null,
                sharedText = created.shareText,
            ) as LaunchIntentRequest.JoinInvitation
            val viewModel = JoinFamilyLedgerViewModel(repository)

            viewModel.consumeSharedInvitation(request.sharedText)
            val previewed = viewModel.uiState.first { it.preview != null || it.error != null }

            assertNull(previewed.error)
            assertEquals("inv_RAW_FALLBACK", previewed.invitationInput)
            assertEquals(InvitationSessionTarget.CurrentServer, previewed.target)
            assertEquals(listOf("https://api.example.com"), factory.baseUrls)
            assertNull(factory.tokenProviders.single().invoke(), "preview must stay anonymous")
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun rawShareOnUnboundSessionUsesProvidedDefaultServer() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = invitationApi()
            val factory = LedgerStubApiFactory(api)
            val viewModel = JoinFamilyLedgerViewModel(
                testLedgerRepository(
                    apiClient = factory,
                    settingsStore = LedgerFakeSettingsStore(),
                    tokenStore = LedgerFakeTokenStore(),
                    expenseDao = LedgerFakeDao(),
                ),
            )

            viewModel.consumeSharedInvitation(
                sharedText = "inv_RAW_DEFAULT",
                defaultServerUrl = "https://default.example.com",
            )
            val previewed = viewModel.uiState.first { it.preview != null || it.error != null }

            assertNull(previewed.error)
            assertEquals("inv_RAW_DEFAULT", previewed.invitationInput)
            assertEquals("https://default.example.com", previewed.serverUrl)
            assertEquals(InvitationSessionTarget.Unbound, previewed.target)
            assertEquals(listOf("https://default.example.com"), factory.baseUrls)
            assertNull(factory.tokenProviders.single().invoke(), "preview must stay anonymous")
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun rawShareOnUnboundSessionWithoutAddressKeepsInputForServerEntry() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = invitationApi()
            val viewModel = viewModel(api, LedgerFakeSettingsStore(), LedgerFakeTokenStore())

            viewModel.consumeSharedInvitation("inv_RAW_NEEDS_SERVER")
            advanceUntilIdle()

            assertNull(viewModel.uiState.value.error)
            assertNull(viewModel.uiState.value.preview)
            assertEquals("inv_RAW_NEEDS_SERVER", viewModel.uiState.value.invitationInput)
            assertEquals("", viewModel.uiState.value.serverUrl)
            assertTrue(api.previewRequests.isEmpty())
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun sharedLinkAutoPreviewsAndUnboundAcceptNeedsOnlyDisplayName() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = invitationApi()
            val store = LedgerFakeSettingsStore()
            val tokenStore = LedgerFakeTokenStore()
            val viewModel = viewModel(api, store, tokenStore)

            viewModel.consumeSharedInvitation(INVITE_URL)
            val previewed = viewModel.uiState.first { it.preview != null || it.error != null }

            assertNull(previewed.error)
            assertEquals("", previewed.invitationInput, "token-bearing link must not be rendered")
            assertEquals("join.example.com", previewed.sourceHost)
            assertEquals(InvitationSessionTarget.Unbound, previewed.target)
            assertTrue(previewed.accountNameRequired)

            viewModel.onAccountNameChanged("新成员")
            var accepted = false
            var consumed = false
            viewModel.acceptCurrentInvitation(
                onAccepted = { accepted = true },
                onConsumed = { consumed = true },
            )
            val done = viewModel.uiState.first { it.success != null || it.error != null }
            advanceUntilIdle()

            assertNull(done.error)
            assertTrue(accepted)
            assertTrue(consumed)
            assertEquals("inv_VM", api.acceptRequests.single().inviteToken)
            assertEquals("新成员", api.acceptRequests.single().accountName)
            assertEquals("测试 Android 设备", api.acceptRequests.single().deviceName)
            assertEquals("https://join.example.com", tokenStore.sessionStore.currentSession()?.serverUrl)
            assertNull(store.serverUrl(), "session authority must stay in LocalSessionStore")
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun boundAliasPreviewAcceptsThroughCurrentSessionWithoutDuplicateIdentity() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = invitationApi()
            val tokenStore = ownerSession()
            val factory = LedgerStubApiFactory(api)
            val repository = testLedgerRepository(
                apiClient = factory,
                settingsStore = LedgerFakeSettingsStore(),
                tokenStore = tokenStore,
                expenseDao = LedgerFakeDao(),
            )
            val viewModel = JoinFamilyLedgerViewModel(repository)

            viewModel.consumeSharedInvitation(INVITE_URL)
            val previewed = viewModel.uiState.first { it.preview != null || it.error != null }
            assertEquals(InvitationSessionTarget.CurrentServer, previewed.target)
            assertFalse(previewed.accountNameRequired)

            viewModel.acceptCurrentInvitation(onAccepted = {})
            viewModel.uiState.first { it.success != null || it.error != null }

            assertEquals(listOf("https://join.example.com", "https://api.example.com"), factory.baseUrls.take(2))
            assertNull(factory.tokenProviders[0].invoke(), "alias preview must be anonymous")
            assertEquals("old-token", factory.tokenSnapshots[1], "accept must use current binding")
            assertNull(api.acceptRequests.single().accountName)
            assertNull(api.acceptRequests.single().deviceName)
            assertEquals("old-token", tokenStore.getToken())
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun foreignServerPreviewRefusesAppAcceptAndKeepsBrowserContinuation() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = invitationApi(
                preview = preview(serverId = FOREIGN_SERVER_ID, generation = FOREIGN_GENERATION),
            )
            val tokenStore = ownerSession()
            val viewModel = viewModel(api, LedgerFakeSettingsStore(), tokenStore)

            viewModel.consumeSharedInvitation(INVITE_URL)
            val previewed = viewModel.uiState.first { it.preview != null || it.error != null }
            assertEquals(InvitationSessionTarget.ForeignServer, previewed.target)
            assertFalse(previewed.canAccept)
            assertTrue(previewed.canContinueInBrowser)

            viewModel.acceptCurrentInvitation(onAccepted = {})
            advanceUntilIdle()
            assertTrue(api.acceptRequests.isEmpty())
            assertEquals("old-token", tokenStore.getToken())

            var opened: String? = null
            assertTrue(viewModel.continueInBrowser { opened = it })
            assertEquals(INVITE_URL, opened)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun invalidTextShareShowsFeedbackAndNeverCallsPreview() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = invitationApi()
            val viewModel = viewModel(api, LedgerFakeSettingsStore(), LedgerFakeTokenStore())

            viewModel.consumeSharedInvitation("这不是邀请")
            advanceUntilIdle()

            assertNotNull(viewModel.uiState.value.error)
            assertEquals("", viewModel.uiState.value.invitationInput)
            assertTrue(api.previewRequests.isEmpty())
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun sharedLinkPreviewFailureCanRetryWithoutRenderingTheToken() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            var attempts = 0
            val api = StubApi(
                LedgerStubApiState(
                    previewHandler = {
                        attempts += 1
                        if (attempts == 1) throw IOException("offline")
                        preview()
                    },
                ),
            )
            val viewModel = viewModel(api, LedgerFakeSettingsStore(), LedgerFakeTokenStore())

            viewModel.consumeSharedInvitation(INVITE_URL)
            val failed = viewModel.uiState.first { it.error != null }
            assertEquals("", failed.invitationInput)
            assertEquals("join.example.com", failed.sourceHost)

            viewModel.previewCurrentInput()
            viewModel.uiState.first { it.previewing }
            val retried = viewModel.uiState.first { !it.previewing && (it.preview != null || it.error != null) }

            assertNotNull(retried.preview)
            assertNull(retried.error)
            assertEquals(2, api.previewRequests.size)
        } finally {
            advanceUntilIdle()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun stalePreviewCannotReturnAfterInvitationInputChanges() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val releaseOld = CompletableDeferred<Unit>()
        try {
            val oldStarted = CompletableDeferred<Unit>()
            val api = StubApi(
                LedgerStubApiState(
                    previewHandler = { request ->
                        if (request.inviteToken == "inv_old") {
                            oldStarted.complete(Unit)
                            releaseOld.await()
                            preview(ledgerName = "旧邀请")
                        } else {
                            preview(ledgerName = "新邀请")
                        }
                    },
                ),
            )
            val viewModel = viewModel(api, LedgerFakeSettingsStore(), LedgerFakeTokenStore())

            viewModel.consumeSharedInvitation(
                "https://old.example.com/web/auth/join#invite=inv_old",
            )
            oldStarted.await()
            viewModel.consumeSharedInvitation(
                "https://new.example.com/web/auth/join#invite=inv_new",
            )
            viewModel.uiState.first { it.preview?.ledgerName == "新邀请" || it.error != null }
            releaseOld.complete(Unit)
            advanceUntilIdle()

            assertEquals("新邀请", viewModel.uiState.value.preview?.ledgerName)
            assertEquals("new.example.com", viewModel.uiState.value.sourceHost)
        } finally {
            releaseOld.complete(Unit)
            advanceUntilIdle()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun newShareWaitsForInFlightAcceptInsteadOfStealingItsRequest() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val releaseAccept = CompletableDeferred<Unit>()
        try {
            val acceptStarted = CompletableDeferred<Unit>()
            val api = StubApi(
                LedgerStubApiState(
                    previewHandler = { request -> preview(ledgerName = request.inviteToken) },
                    acceptHandler = {
                        acceptStarted.complete(Unit)
                        releaseAccept.await()
                        acceptedResponse()
                    },
                ),
            )
            val viewModel = viewModel(api, LedgerFakeSettingsStore(), ownerSession())
            viewModel.consumeSharedInvitation(
                "https://old.example.com/web/auth/join#invite=inv_old",
            )
            viewModel.uiState.first { it.preview?.ledgerName == "inv_old" }

            var oldConsumed = false
            viewModel.acceptCurrentInvitation(onAccepted = {}, onConsumed = { oldConsumed = true })
            acceptStarted.await()
            viewModel.consumeSharedInvitation(
                "https://new.example.com/web/auth/join#invite=inv_new",
            )
            releaseAccept.complete(Unit)
            val next = viewModel.uiState.first {
                it.sourceHost == "new.example.com" && (it.preview != null || it.error != null)
            }

            assertNull(next.error)
            assertEquals("inv_new", next.preview?.ledgerName)
            assertTrue(oldConsumed)
            assertEquals(listOf("inv_old"), api.acceptRequests.map { it.inviteToken })
        } finally {
            releaseAccept.complete(Unit)
            advanceUntilIdle()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun resetClearsInputAndPreviewTogether() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val viewModel = viewModel(invitationApi(), LedgerFakeSettingsStore(), LedgerFakeTokenStore())
            viewModel.onInvitationInputChanged("inv_manual")
            viewModel.reset("https://default.example.com")

            assertEquals(
                JoinFamilyLedgerUiState(serverUrl = "https://default.example.com"),
                viewModel.uiState.value,
            )
        } finally {
            Dispatchers.resetMain()
        }
    }

    private fun viewModel(
        api: StubApi,
        store: LedgerFakeSettingsStore,
        tokenStore: LedgerFakeTokenStore,
    ): JoinFamilyLedgerViewModel = JoinFamilyLedgerViewModel(
        testLedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = tokenStore,
            expenseDao = LedgerFakeDao(),
        ),
    )

    private fun invitationApi(
        preview: InvitationPreviewResponseDto = preview(),
    ) = StubApi(
        LedgerStubApiState(
            previewResult = preview,
            acceptResult = acceptedResponse(),
        ),
    )

    private fun acceptedResponse() = InvitationAcceptResponseDto(
        sessionToken = "tk_joined",
        serverId = TEST_SERVER_ID,
        dataGeneration = TEST_DATA_GENERATION,
        accountPublicId = TEST_ACCOUNT_PUBLIC_ID,
        devicePublicId = TEST_DEVICE_PUBLIC_ID,
        accountName = "新成员",
        ledgerId = "L_family",
        ledgerName = "家庭账本",
        deviceName = "测试 Android 设备",
        role = "member",
    )

    private fun ownerSession() = existingOwnerSessionFixture(
        ledgerId = "L_personal",
        ledgerName = "个人账本",
        accountName = "原成员",
        deviceName = "原手机",
        token = "old-token",
    )

    private fun preview(
        serverId: String = TEST_SERVER_ID,
        generation: String = TEST_DATA_GENERATION,
        ledgerName: String = "家庭账本",
    ) = InvitationPreviewResponseDto(
        serverId = serverId,
        dataGeneration = generation,
        ledgerId = "L_family",
        ledgerName = ledgerName,
        role = "member",
        expiresAt = "2026-07-01T00:00:00Z",
    )

    private companion object {
        const val INVITE_URL = "https://join.example.com/web/auth/join#invite=inv_VM"
        const val FOREIGN_SERVER_ID = "00000000-0000-0000-0000-000000000010"
        const val FOREIGN_GENERATION = "00000000-0000-0000-0000-000000000011"
    }
}
