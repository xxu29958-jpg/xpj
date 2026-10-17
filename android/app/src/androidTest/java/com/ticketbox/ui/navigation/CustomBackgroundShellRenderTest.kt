package com.ticketbox.ui.navigation

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Path
import android.graphics.Shader
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
import com.ticketbox.ui.appearance.background.ImmersiveBackgroundScaffold
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.theme.TicketboxTheme
import java.io.File
import kotlin.random.Random
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
        val scene = photo("scene", 1600, 1000, ::paintScene)
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
            "pale" to photo("pale", 1080, 1920, ::paintPale),
            "dark" to photo("dark", 1080, 1920, ::paintDark),
            "saturated" to photo("saturated", 1600, 1000, ::paintSaturated),
            "busy" to photo("busy", 1200, 1200, ::paintBusy),
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

    private fun photo(name: String, width: Int, height: Int, paint: (Canvas, Int, Int) -> Unit): File {
        val file = File(context.filesDir, "background-fixture-$name.png")
        val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
        paint(Canvas(bitmap), width, height)
        file.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
        bitmap.recycle()
        photos += file
        return file
    }

    private fun paintScene(canvas: Canvas, width: Int, height: Int) {
        val w = width.toFloat()
        val h = height.toFloat()
        canvas.drawRect(0f, 0f, w, h, Paint().apply {
            shader = LinearGradient(0f, 0f, 0f, h * 0.6f, 0xFF8EC3E6.toInt(), 0xFFF7E3C2.toInt(), Shader.TileMode.CLAMP)
        })
        canvas.drawCircle(w * 0.72f, h * 0.30f, h * 0.09f, Paint(Paint.ANTI_ALIAS_FLAG).apply { color = 0xFFFFD27A.toInt() })
        fun hill(color: Int, base: Float, peak: Float, shift: Float) = canvas.drawPath(Path().apply {
            moveTo(0f, h); lineTo(0f, h * base)
            quadTo(w * (0.3f + shift), h * peak, w * 0.6f, h * base)
            quadTo(w * (0.85f + shift), h * (base + 0.08f), w, h * (base - 0.05f))
            lineTo(w, h); close()
        }, Paint(Paint.ANTI_ALIAS_FLAG).apply { this.color = color })
        hill(0xFF5E8C5A.toInt(), 0.62f, 0.38f, 0f)
        hill(0xFF2F5D3A.toInt(), 0.74f, 0.52f, 0.1f)
        canvas.drawRect(0f, h * 0.86f, w, h, Paint().apply { color = 0xFF3E7CA6.toInt() })
    }

    private fun paintPale(canvas: Canvas, width: Int, height: Int) {
        canvas.drawRect(0f, 0f, width.toFloat(), height.toFloat(), Paint().apply {
            shader = LinearGradient(0f, 0f, 0f, height.toFloat(), 0xFFFFFFFF.toInt(), 0xFFF1EADF.toInt(), Shader.TileMode.CLAMP)
        })
        val cloud = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = 0xFFEDE7F6.toInt() }
        listOf(0.2f to 0.18f, 0.7f to 0.42f, 0.35f to 0.7f).forEach { (x, y) ->
            canvas.drawCircle(width * x, height * y, width * 0.22f, cloud)
        }
    }

    private fun paintDark(canvas: Canvas, width: Int, height: Int) {
        canvas.drawRect(0f, 0f, width.toFloat(), height.toFloat(), Paint().apply {
            shader = LinearGradient(0f, 0f, 0f, height.toFloat(), 0xFF0B0E14.toInt(), 0xFF1B2233.toInt(), Shader.TileMode.CLAMP)
        })
        val random = Random(7)
        val light = Paint(Paint.ANTI_ALIAS_FLAG)
        repeat(260) {
            light.color = if (random.nextBoolean()) 0xFFFFC86B.toInt() else 0xFFE8F1FF.toInt()
            canvas.drawCircle(random.nextFloat() * width, height * (0.45f + random.nextFloat() * 0.55f), 2f + random.nextFloat() * 5f, light)
        }
    }

    private fun paintSaturated(canvas: Canvas, width: Int, height: Int) {
        val colors = listOf(0xFFE53935, 0xFFFB8C00, 0xFFFDD835, 0xFF43A047, 0xFF1E88E5, 0xFF8E24AA)
        val band = width / colors.size.toFloat()
        colors.forEachIndexed { index, color ->
            canvas.drawRect(index * band, 0f, (index + 1) * band, height.toFloat(), Paint().apply { this.color = color.toInt() })
        }
    }

    private fun paintBusy(canvas: Canvas, width: Int, height: Int) {
        val random = Random(11)
        val paint = Paint()
        repeat(2400) {
            paint.color = (0xFF000000 or random.nextLong(0xFFFFFF)).toInt()
            val x = random.nextFloat() * width
            val y = random.nextFloat() * height
            canvas.drawRect(x, y, x + 6f + random.nextFloat() * 40f, y + 4f + random.nextFloat() * 18f, paint)
        }
        paint.color = 0xFF111111.toInt()
        paint.strokeWidth = 2f
        var y = 0f
        while (y < height) {
            canvas.drawLine(0f, y, width.toFloat(), y, paint)
            y += 22f
        }
    }

    private companion object {
        const val DECODE_SETTLE_MS = 700L
    }
}
