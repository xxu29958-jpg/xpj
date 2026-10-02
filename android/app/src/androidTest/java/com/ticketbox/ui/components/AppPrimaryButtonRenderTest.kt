package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * eb49 实机鬼影反例（tmp/w2c/eb49-composer-retry-settled.png）：新建欠款抽屉内币种
 * 未决 → 禁用保存；重试成功同一帧「提示行移除 + 保存键 disabled→enabled」后，
 * enabled=true 且可点击，但 teal 填充/描边永久丢失、深色文字近不可见。
 * 本测试镜像该精确状态翻转（sheet 内、兄弟行同帧移除、按钮翻转），合同：
 * 禁用与启用两态盒体填充都必须真实绘制（现行渲染：只有内容变淡、盒体不变），
 * 且翻转后 enabled 语义与点击保持可用。
 */
@OptIn(ExperimentalMaterial3Api::class)
class AppPrimaryButtonRenderTest {

    @get:Rule
    val composeRule = createComposeRule()

    private class Harness {
        var currencyResolved by mutableStateOf(false)
        var clicks = 0
        var primary = Color.Unspecified
    }

    private fun setSheet(harness: Harness) {
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Midnight) {
                harness.primary = LocalThemeVisuals.current.primary
                ModalBottomSheet(
                    onDismissRequest = {},
                    sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
                ) {
                    Column(modifier = Modifier.padding(24.dp)) {
                        // 镜像生产：币种未决提示行，在重试成功的同一帧被移除
                        if (!harness.currencyResolved) {
                            Text(text = "currency unresolved", modifier = Modifier.testTag(BANNER_TAG))
                        }
                        AppPrimaryButton(
                            text = SAVE_TEXT,
                            icon = Icons.Filled.Check,
                            modifier = Modifier.fillMaxWidth().testTag(BUTTON_TAG),
                            enabled = harness.currencyResolved,
                            onClick = { harness.clicks++ },
                        )
                    }
                }
            }
        }
        composeRule.waitForIdle()
    }

    @Test
    fun disabledToEnabledRetainsContainerFillSemanticsAndClick() {
        val harness = Harness()
        setSheet(harness)

        // 基线对照：禁用态盒体填充必须在绘（若此断言也失败，说明捕获通道本身坏了而非产品 RED）
        assertContainerFilled(stage = "disabled", harness = harness)

        // 同一状态翻转：提示行移除 + 按钮 disabled→enabled（生产鬼影帧的精确条件）
        composeRule.runOnIdle { harness.currencyResolved = true }
        composeRule.waitForIdle()

        assertContainerFilled(stage = "enabled", harness = harness)
        composeRule.onNodeWithTag(BUTTON_TAG).assertIsEnabled().performClick()
        composeRule.waitForIdle()
        assertEquals(1, harness.clicks)
    }

    @Test
    fun pairedActionsKeepTheirCompleteLabelsAtLargeFont() {
        val skin = mutableStateOf(AppSkin.Paper)
        val primaryLabel = "确认并保存账单"
        val secondaryLabel = "核对当前事实后重新拟定"
        var primaryClicks = 0
        var secondaryClicks = 0
        var controlFontSize = TextUnit.Unspecified
        composeRule.setContent {
            val density = LocalDensity.current
            CompositionLocalProvider(LocalDensity provides Density(density.density, fontScale = 1.8f)) {
                TicketboxTheme(skin = skin.value) {
                    controlFontSize = MaterialTheme.typography.labelLarge.fontSize
                    Row(Modifier.width(328.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        AppSecondaryButton(
                            text = secondaryLabel, modifier = Modifier.weight(1f).testTag("secondary"),
                            onClick = { secondaryClicks++ },
                        )
                        AppPrimaryButton(
                            text = primaryLabel, icon = Icons.Filled.Check,
                            modifier = Modifier.weight(1f).testTag(BUTTON_TAG),
                            onClick = { primaryClicks++ },
                        )
                    }
                }
            }
        }
        for (theme in listOf(AppSkin.Paper, AppSkin.Midnight)) {
            composeRule.runOnIdle { skin.value = theme }
            for (label in listOf(primaryLabel, secondaryLabel)) {
                val layouts = mutableListOf<TextLayoutResult>()
                composeRule.onNodeWithText(label, useUnmergedTree = true)
                    .performSemanticsAction(SemanticsActions.GetTextLayoutResult) { it(layouts) }
                assertTrue("The complete action must be rendered", layouts.isNotEmpty())
                for (layout in layouts) {
                    assertEquals("Action text must respect the user's text size",
                        controlFontSize, layout.layoutInput.style.fontSize)
                    assertFalse("The action label must fit its height", layout.didOverflowHeight)
                    for (line in 0 until layout.lineCount) {
                        assertFalse("Action words must not be ellipsized", layout.isLineEllipsized(line))
                        assertTrue(layout.getLineLeft(line) >= 0f && layout.getLineRight(line) <= layout.size.width)
                    }
                }
            }
            saveConsumerArtPreview("paired-actions-${theme.name}-large-font",
                composeRule.onRoot().captureToImage().asAndroidBitmap())
            composeRule.onNodeWithTag(BUTTON_TAG).assertIsEnabled().performClick()
            composeRule.onNodeWithTag("secondary").assertIsEnabled().performClick()
        }
        assertEquals(2, primaryClicks)
        assertEquals(2, secondaryClicks)
    }

    private fun assertContainerFilled(stage: String, harness: Harness) {
        val expected = harness.primary
        assertTrue("harness 应读到真实 primary 色", expected != Color.Unspecified)
        val bitmap = composeRule.onNodeWithTag(BUTTON_TAG).captureToImage().asAndroidBitmap()
        val sampleX = listOf(0.08f, 0.2f, 0.92f).map { (bitmap.width * it).toInt() }
        val sampleY = listOf(0.5f, 0.8f).map { (bitmap.height * it).toInt() }
        for (x in sampleX) {
            for (y in sampleY) {
                val pixel = Color(bitmap.getPixel(x, y))
                assertTrue(
                    "$stage 态主键填充丢失：($x,$y)=$pixel 偏离 primary=$expected",
                    pixel.isCloseTo(expected),
                )
            }
        }
    }

    private fun Color.isCloseTo(other: Color): Boolean =
        listOf(red - other.red, green - other.green, blue - other.blue).all { diff ->
            diff > -CHANNEL_TOLERANCE && diff < CHANNEL_TOLERANCE
        }

    private companion object {
        const val BUTTON_TAG = "app_primary_button_under_test"
        const val BANNER_TAG = "currency_unresolved_banner"
        const val SAVE_TEXT = "保存"
        const val CHANNEL_TOLERANCE = 12f / 255f
    }
}
