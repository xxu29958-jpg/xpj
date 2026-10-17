package com.ticketbox.ui.navigation

import android.content.Context
import android.graphics.Canvas
import androidx.annotation.StringRes
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onFirst
import androidx.compose.ui.test.performClick
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.AppThemeMode
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.ui.appearance.background.ControlledPhotos
import com.ticketbox.ui.appearance.background.ImmersiveBackgroundScaffold
import com.ticketbox.ui.appearance.background.writeControlledPhoto
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.theme.TicketboxTheme
import java.io.File
import org.junit.After
import org.junit.Test
import org.junit.Rule

/**
 * Real shell pages over the shared background layer, with deterministic synthetic photos only.
 * Captures are visual evidence for background visibility and readability; no user image is used.
 */
class CustomBackgroundShellRenderTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val harness = FactEntryNavigationHarness(context)
    private val settings = mutableStateOf(BackgroundSettings())
    private val skin = mutableStateOf(AppSkin.Paper)
    private val photos = mutableListOf<File>()

    @After fun close() {
        photos.forEach(File::delete)
        harness.close()
    }

    @Test fun controlledPhotosAcrossDomainsImmersionAndSkins() {
        mount()
        val scene = photo("scene", 1600, 1000, ControlledPhotos::scene)
        for (mode in ImmersionMode.entries) {
            show(scene, mode)
            mapOf("inbox" to R.string.nav_domain_inbox, "transactions" to R.string.nav_domain_transactions,
                "insights" to R.string.nav_domain_insights).forEach { (key, domain) ->
                open(domain)
                capture("bg-scene-${mode.storageKey}-$key")
            }
        }
        show(scene, ImmersionMode.Balanced)
        open(R.string.nav_domain_obligations)
        capture("bg-scene-balanced-relations")
        open(R.string.nav_domain_plans)
        capture("bg-scene-balanced-plans")

        open(R.string.nav_domain_inbox)
        mapOf(
            "pale" to photo("pale", 1080, 1920, ControlledPhotos::pale),
            "dark" to photo("dark", 1080, 1920, ControlledPhotos::dark),
            "saturated" to photo("saturated", 1600, 1000, ControlledPhotos::saturated),
            "busy" to photo("busy", 1200, 1200, ControlledPhotos::busy),
        ).forEach { (name, file) ->
            show(file, ImmersionMode.Balanced)
            capture("bg-$name-balanced-inbox")
        }

        compose.runOnIdle { skin.value = AppSkin.Midnight }
        show(photos.first { it.name.contains("dark") }, ImmersionMode.Balanced)
        capture("bg-midnight-dark-balanced-inbox")
        open(R.string.nav_domain_transactions)
        capture("bg-midnight-dark-balanced-transactions")
        show(scene, ImmersionMode.Atmosphere)
        capture("bg-midnight-scene-atmosphere-transactions")
    }

    private fun show(photo: File, mode: ImmersionMode) {
        compose.runOnIdle {
            settings.value = BackgroundSettings(enableParallax = false).withCustomImage(photo.absolutePath).copy(immersionMode = mode)
        }
        // Decoding runs off the main thread; give it a bounded moment before the screenshot.
        Thread.sleep(DECODE_SETTLE_MS)
        compose.waitForIdle()
    }

    private fun open(@StringRes label: Int) {
        compose.onAllNodes(hasContentDescription(context.getString(label)) and hasClickAction()).onFirst().performClick()
        compose.waitForIdle()
    }

    private fun capture(name: String) {
        compose.waitForIdle()
        val automation = InstrumentationRegistry.getInstrumentation().uiAutomation
        automation.waitForIdle(250, 5_000)
        saveConsumerArtPreview(name, requireNotNull(automation.takeScreenshot()))
    }

    private fun mount() {
        compose.setContent {
            CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                TicketboxTheme(skin = skin.value) {
                    val controller = rememberNavController()
                    val entry by controller.currentBackStackEntryAsState()
                    ImmersiveBackgroundScaffold(settings.value, skin.value, harness.shell.surfaceRole(entry?.destination?.route)) {
                        MainNavGraph(MainNavigationRuntime(controller, harness.shell, harness.screenFactory), remember { SnackbarHostState() },
                            SettingsPreferenceControls(skin.value, AppThemeMode.System, CurrencyCode.CNY,
                                onThemeModeChange = {}, onCurrencyChange = {}), onBindingCleared = {})
                    }
                }
            }
        }
        compose.waitForIdle()
    }

    private fun photo(name: String, width: Int, height: Int, paint: (Canvas, Int, Int) -> Unit): File =
        writeControlledPhoto(File(context.filesDir, "background-fixture-$name.png"), width, height, paint).also { photos += it }

    private companion object {
        const val DECODE_SETTLE_MS = 2_000L
    }
}
