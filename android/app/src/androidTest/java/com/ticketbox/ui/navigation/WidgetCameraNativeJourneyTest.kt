package com.ticketbox.ui.navigation

import android.content.Context
import android.os.Bundle
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.theme.TicketboxTheme
import java.io.File
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

/** The QA driver operates the actual emulator camera through fresh accessibility bounds. */
class WidgetCameraNativeJourneyTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val harness = FactEntryNavigationHarness(context)
    private val mounted = mutableStateOf(true)
    private val captureDirectory = File(context.filesDir, "receipt-captures")

    @After fun close() {
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun cancellingThenTakingARealCameraPhotoUsesTheOriginalUploadQueue() {
        val before = captures()
        compose.setContent {
            CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                TicketboxTheme(skin = AppSkin.Default) {
                    if (mounted.value) {
                        val nav = rememberNavController()
                        NavHost(nav, startDestination = "camera-inbox") {
                            composable("camera-inbox") { PendingRoute(nav, harness.shell, harness.screenFactory) }
                        }
                    }
                }
            }
        }
        compose.runOnIdle { dispatchShortcutNavigation(ShortcutTarget.CaptureReceipt, harness.shell) }
        compose.waitUntil(15_000) { (captures() - before).isNotEmpty() }
        phase("cancel_camera")
        compose.waitUntil(120_000) { captures() == before }
        assertTrue(harness.fixture.stored().isEmpty())
        compose.runOnIdle { dispatchShortcutNavigation(ShortcutTarget.CaptureReceipt, harness.shell) }
        compose.waitUntil(15_000) { (captures() - before).isNotEmpty() }
        phase("take_and_accept_photo")
        compose.waitUntil(120_000) { harness.fixture.stored().any { it["type"] == PendingMutationType.UploadScreenshot.wireValue } }
        val observation = runBlocking { harness.fixture.uploadIntents.observeUploadIntents().first { it.uploads.isNotEmpty() } }
        assertEquals(1, observation.uploads.size)
        assertNotNull(observation.uploads.single().payload?.file)
        assertEquals(harness.screenFactory.repository.captureDeferredLedgerBinding(), observation.access?.binding)
        compose.waitUntil(10_000) { captures() == before }
        phase("camera_upload_saved")
    }

    private fun captures() = captureDirectory.listFiles().orEmpty().map { it.name }.toSet()
    private fun phase(value: String) = InstrumentationRegistry.getInstrumentation().sendStatus(0, Bundle().apply { putString("camera_phase", value) })
}
