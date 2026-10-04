package com.ticketbox.ui.screens.settings

import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertIsOff
import androidx.compose.ui.test.assertIsOn
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.unit.Density
import com.ticketbox.domain.model.AppThemeMode
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.AppearanceUiState
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class AppearanceScreenTest {
    @get:Rule val compose = createComposeRule()

    @Test fun themeBackgroundAndMotionChoicesKeepTheirOriginalActions() {
        var settings by mutableStateOf(BackgroundSettings())
        var mode by mutableStateOf(AppThemeMode.Paper)
        var scale by mutableStateOf(1f)
        var gallery = 0
        var album = 0
        var edited: BackgroundSettings? = null
        var currency by mutableStateOf(CurrencyCode.CNY)
        compose.setContent {
            val skin = mode.resolveSkin(false)
            CompositionLocalProvider(LocalDensity provides Density(LocalDensity.current.density, scale)) {
                TicketboxTheme(skin = skin) {
                    AppearanceScreen(
                        AppearanceScreenState(AppearanceUiState(backgroundSettings = settings),
                            AppearancePreferenceState(skin, mode, currency)),
                        AppearanceScreenActions({},
                            AppearancePreferenceActions({ mode = it }, { currency = it }),
                            AppearanceBackgroundActions({ gallery++ }, { album++ },
                                { edited = it }, { settings = settings.withoutBackground() }),
                            AppearanceImmersionActions(
                                { settings = settings.copy(immersionMode = it) },
                                { settings = settings.copy(enableParallax = it) },
                                { settings = settings.copy(reduceMotion = it) })),
                    )
                }
            }
        }
        compose.onNodeWithText("本月净支出 · 示例").assertIsDisplayed()
        capture("appearance-paper")
        compose.onNodeWithText("调整构图").performScrollTo().assertIsNotEnabled()
        compose.onNodeWithText("背景图库").performScrollTo().performClick()
        compose.onNodeWithText("从相册选择").performScrollTo().performClick()
        compose.runOnIdle {
            assertEquals(1, gallery); assertEquals(1, album)
            settings = settings.withBuiltInBackground("paper_warm")
        }
        compose.onNodeWithText("当前背景：茶雾").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("调整构图").performScrollTo().performClick()
        compose.runOnIdle { assertEquals(settings, edited) }
        compose.onNodeWithText("专注").performScrollTo().performClick()
        compose.runOnIdle { assertEquals(ImmersionMode.Focus, settings.immersionMode) }
        compose.onNodeWithContentDescription("减少动效").performScrollTo().assertIsOff().performClick().assertIsOn()
        compose.onNodeWithContentDescription("视差动效").performScrollTo().assertIsOff().assertIsNotEnabled()
        compose.runOnIdle { assertEquals(true, settings.enableParallax); assertEquals(true, settings.reduceMotion) }
        capture("appearance-motion-paper")
        compose.onNodeWithText("默认记账币种").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("玄夜").performScrollTo().performClick()
        compose.runOnIdle { assertEquals(AppThemeMode.Midnight, mode); scale = 1.8f }
        compose.onNodeWithText("挑一种喜欢的感觉").performScrollTo().assertIsDisplayed()
        capture("appearance-midnight-large")
        compose.onNodeWithText("恢复主题背景").performScrollTo().performClick().assertIsNotEnabled()
        compose.onNodeWithText("当前背景：跟随主题").performScrollTo().assertIsDisplayed()
        capture("appearance-theme-restored-large")
    }

    private fun capture(name: String) = saveConsumerArtPreview(name, compose.onRoot().captureToImage().asAndroidBitmap())
}
