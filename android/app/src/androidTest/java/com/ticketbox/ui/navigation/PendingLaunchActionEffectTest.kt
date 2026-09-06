package com.ticketbox.ui.navigation

import android.app.Activity
import android.content.Intent
import android.net.Uri
import androidx.activity.compose.LocalActivityResultRegistryOwner
import androidx.activity.result.ActivityResultRegistry
import androidx.activity.result.ActivityResultRegistryOwner
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContract
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.ViewModelStore
import androidx.core.app.ActivityOptionsCompat
import androidx.test.core.app.ApplicationProvider
import androidx.test.filters.SdkSuppress
import com.ticketbox.RepositoryGraph
import com.ticketbox.data.repository.UploadIntentConnectedFixture
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.screens.PendingScreen
import com.ticketbox.ui.screens.pending.PendingDuplicateReviewActions
import com.ticketbox.ui.screens.pending.PendingExpenseQueueActions
import com.ticketbox.ui.screens.pending.PendingQueueReviewActions
import com.ticketbox.ui.screens.pending.PendingQuickFixEntryActions
import com.ticketbox.ui.screens.pending.PendingReviewFlowActions
import com.ticketbox.ui.screens.pending.PendingReviewSheetHostActions
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.upload.PreparedUploadImage
import com.ticketbox.viewmodel.PendingViewModel
import com.ticketbox.viewmodel.RepositoryViewModelRepositories
import com.ticketbox.viewmodel.repositoryViewModelFactory
import java.util.concurrent.CopyOnWriteArrayList
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class PendingLaunchActionEffectTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun consumedShareSurvivesRouteReentryAndActualRetryContinuesTheOriginalTail() {
        val shell = MainShellState()
        val actions = PendingUploadConnectedActions()
        val prepared = CopyOnWriteArrayList<String>()
        val releaseA = CompletableDeferred<Unit>()
        val visible = mutableStateOf(true)
        lateinit var vm: PendingViewModel
        composeRule.setContent {
            val owner = remember { PendingViewModel(actions) }
            vm = owner
            DisposableEffect(owner) { onDispose { owner.viewModelScope.cancel() } }
            val state by owner.uiState.collectAsState()
            if (visible.value) {
                PendingLaunchActionEffect(shell, state.canStartUpload, { false }) { refs ->
                    owner.acceptUploads(refs) { name ->
                        prepared += name
                        if (name == "a.jpg") releaseA.await()
                        preparedImage(name)
                    }
                }
                TicketboxTheme(skin = AppSkin.Default) {
                    PendingScreen(state, pendingScreenChromeActions(
                        owner, {}, PendingInboxNavigationActions({}, {}), shell.pendingFilterRequest,
                    ), PendingExpenseQueueActions({}, {}, {}, {}), unusedReviewActions(), unusedSheetActions())
                }
            }
        }
        composeRule.runOnIdle {
            shell.launchAction.post(LaunchAction.UploadSharedImages(listOf("a.jpg", "b.jpg")))
        }
        composeRule.waitUntil(timeoutMillis = 5_000) { prepared == listOf("a.jpg") }
        composeRule.runOnIdle {
            assertNull(shell.launchAction.pending)
            shell.launchAction.post(LaunchAction.UploadSharedImages(listOf("c.jpg")))
        }
        composeRule.runOnIdle {
            assertNull(shell.launchAction.pending)
            visible.value = false
        }
        releaseA.complete(Unit)
        composeRule.waitUntil(timeoutMillis = 5_000) { vm.uiState.value.canRetryUpload }
        assertEquals(listOf("a.jpg", "b.jpg"), actions.uploadedNames.toList())
        composeRule.runOnIdle { visible.value = true }

        composeRule.onNodeWithText("重试上传").performScrollTo().performClick()
        composeRule.waitUntil(timeoutMillis = 5_000) { vm.uiState.value.items.size == 3 && !vm.uiState.value.uploading }

        assertEquals(listOf("a.jpg", "b.jpg", "b.jpg", "c.jpg"), actions.uploadedNames.toList())
        assertEquals(listOf("a.jpg", "b.jpg", "c.jpg"), prepared.toList())
        composeRule.runOnIdle {
            assertEquals(setOf("a.jpg", "b.jpg", "c.jpg"), vm.uiState.value.items.map { it.merchant }.toSet())
            assertFalse(vm.uiState.value.canRetryUpload)
            assertNull(shell.launchAction.pending)
        }
    }

    @Test
    @SdkSuppress(minSdkVersion = 29)
    fun reopenedRoomAndNewOwnerRecoverConsumedBatchAfterTheSourceUrisAreGone() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        UploadIntentConnectedFixture(context).use { fixture ->
            val graph = mutableStateOf<RepositoryGraph?>(fixture.reopen())
            var vm: PendingViewModel? = null
            lateinit var shell: MainShellState
            try {
                val refs = fixture.createSources()
                composeRule.setContent {
                    graph.value?.let { repositories ->
                        val currentShell = remember(repositories) { MainShellState() }
                        val store = remember(repositories) { ViewModelStore() }
                        val owner = remember(repositories) { ViewModelProvider(store, repositoryViewModelFactory(
                            RepositoryViewModelRepositories(repositories.expenseRepository, repositories.budgetRepository,
                                repositories.reportsRepository, repositories.debtRepository), currentShell::markInsightsDataChanged,
                        ))[PendingViewModel::class.java] }
                        vm = owner
                        shell = currentShell
                        DisposableEffect(store) { onDispose { store.clear() } }
                        val state by owner.uiState.collectAsState()
                        PendingLaunchActionEffect(currentShell, state.canStartUpload, { false }) { images ->
                            owner.acceptUploads(images, pendingUploadSource(context))
                        }
                        TicketboxTheme(skin = AppSkin.Default) {
                            PendingScreen(state, pendingScreenChromeActions(
                                owner, {}, PendingInboxNavigationActions({}, {}), currentShell.pendingFilterRequest,
                            ), PendingExpenseQueueActions({}, {}, {}, {}), unusedReviewActions(), unusedSheetActions())
                        }
                    }
                }
                composeRule.runOnIdle { shell.launchAction.post(LaunchAction.UploadSharedImages(refs)) }
                composeRule.waitUntil(timeoutMillis = 5_000) {
                    vm?.uiState?.value?.let { it.canRetryUpload && !it.loading && it.items.size == 1 } == true
                }
                assertEquals(listOf("a.png", "b.png"), fixture.network.attempts.map { it.name })
                assertArrayEquals(fixture.sourceBytes.getValue("b.png"), fixture.network.attempts[1].bytes)
                assertEquals(listOf("upload-ledger"), fixture.savedUploadLedgers.toList())
                assertEquals("a.png", requireNotNull(vm).uiState.value.items.single().merchant)
                assertTrue(fixture.hasDiskDatabase())
                val oldOwner = requireNotNull(vm)
                val oldShell = shell
                val oldJob = requireNotNull(oldOwner.viewModelScope.coroutineContext[Job])
                composeRule.runOnIdle {
                    assertNull(oldShell.launchAction.pending)
                    graph.value = null
                }
                composeRule.waitForIdle()
                runBlocking { oldJob.join() }
                fixture.revokeSources()
                val reopened = fixture.reopen()
                composeRule.runOnIdle { graph.value = reopened }
                composeRule.waitUntil(timeoutMillis = 5_000) {
                    vm !== oldOwner && vm?.uiState?.value?.let { it.hasLoadedOnce && !it.loading } == true
                }
                composeRule.runOnIdle {
                    assertTrue(shell !== oldShell)
                    assertNull(shell.launchAction.pending)
                    assertEquals(listOf("a.png"), requireNotNull(vm).uiState.value.items.map { it.merchant })
                }
                composeRule.waitUntil(timeoutMillis = 5_000) { requireNotNull(vm).uiState.value.canRetryUpload }
                composeRule.onNodeWithText("重试上传").performScrollTo().performClick()
                composeRule.waitUntil(timeoutMillis = 5_000) {
                    vm?.uiState?.value?.let { it.items.size == 3 && !it.uploading } == true
                }
                assertEquals(listOf("a.png", "b.png", "b.png", "c.png"), fixture.network.attempts.map { it.name })
                fixture.network.attempts.forEach { assertArrayEquals(fixture.sourceBytes.getValue(it.name), it.bytes) }
                assertFalse(requireNotNull(vm).uiState.value.canRetryUpload)
            } finally {
                composeRule.runOnIdle { graph.value = null; vm?.viewModelScope?.cancel() }
                composeRule.waitForIdle()
                runBlocking { vm?.viewModelScope?.coroutineContext?.get(Job)?.join() }
            }
        }
    }

    @Test
    fun pickerShortcutWaitsWhilePausedAndIsConsumedOnlyWhenOpened() {
        val shell = MainShellState()
        val available = mutableStateOf(false)
        var opens = 0
        composeRule.setContent {
            PendingLaunchActionEffect(shell, available.value, { opens += 1; true }, { error("No shared images") })
        }
        composeRule.runOnIdle { shell.launchAction.post(LaunchAction.OpenImagePicker) }
        composeRule.runOnIdle {
            assertEquals(0, opens)
            assertTrue(shell.launchAction.pending is LaunchAction.OpenImagePicker)
            available.value = true
        }
        composeRule.runOnIdle {
            assertEquals(1, opens)
            assertNull(shell.launchAction.pending)
        }
    }

    @Test
    fun actualPickerResultCancellationIsEmptyAndSelectionUsesTheSharedHandoff() {
        val shell = MainShellState()
        var selected: Uri? = null
        val registry = object : ActivityResultRegistry() {
            override fun <I, O> onLaunch(
                requestCode: Int, contract: ActivityResultContract<I, O>, input: I, options: ActivityOptionsCompat?,
            ) {
                dispatchResult(requestCode, if (selected == null) Activity.RESULT_CANCELED else Activity.RESULT_OK,
                    Intent().setData(selected))
            }
        }
        val registryOwner = object : ActivityResultRegistryOwner {
            override val activityResultRegistry = registry
        }
        lateinit var openPicker: () -> Unit
        composeRule.setContent {
            CompositionLocalProvider(LocalActivityResultRegistryOwner provides registryOwner) {
                val launcher = rememberSingleImageUploadLauncher(shell)
                openPicker = { launcher.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) }
            }
        }
        composeRule.runOnIdle { openPicker() }
        composeRule.runOnIdle {
            assertNull(shell.launchAction.pending)
            selected = Uri.parse("content://ticketbox/picked-receipt")
            openPicker()
        }
        composeRule.runOnIdle {
            assertEquals(LaunchAction.UploadSharedImages(listOf(requireNotNull(selected).toString())),
                shell.launchAction.consume())
            assertNull(shell.launchAction.consume())
        }
    }

    private fun preparedImage(name: String) = PreparedUploadImage(
        fileName = name, contentType = "image/jpeg", bytes = name.encodeToByteArray(),
        sourceSizeBytes = name.length.toLong(),
    )

    private fun unusedReviewActions() = PendingReviewFlowActions(
        PendingQuickFixEntryActions({}, {}, {}), PendingDuplicateReviewActions({}), PendingQueueReviewActions({}, {}),
    )

    private fun unusedSheetActions() = PendingReviewSheetHostActions(
        { _, _ -> }, { _, _ -> }, { _, _ -> }, { _, _ -> }, {}, {}, {}, {}, {},
    )
}
