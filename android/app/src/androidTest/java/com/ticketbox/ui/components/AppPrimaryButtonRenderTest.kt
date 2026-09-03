package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.Assert.assertEquals
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
