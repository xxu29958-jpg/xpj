package com.ticketbox.ui.mascot

import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.design.stateTokensForSkin
import com.ticketbox.ui.design.themeVisualsForSkin
import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * 钉死 MascotPalette 与 brief §7.1 的逐槽位映射:换源/串线(比如把腮红接到
 * primary)直接翻红。跑满三主题,保证映射对 skin 是纯透传、不藏主题分支。
 */
class MascotPaletteTest {

    @Test
    fun paletteMapsEachSlotToItsBriefTokenAcrossAllSkins() {
        AppSkin.entries.forEach { skin ->
            val visuals = themeVisualsForSkin(skin)
            val states = stateTokensForSkin(skin)
            val palette = mascotPalette(visuals, states)
            assertEquals(visuals.warmMist, palette.bodyFill, "bodyFill@$skin")
            assertEquals(visuals.solidCard, palette.bodyHighlight, "bodyHighlight@$skin")
            assertEquals(visuals.textDefault, palette.outline, "outline@$skin")
            assertEquals(visuals.textMuted, palette.wireStroke, "wireStroke@$skin")
            assertEquals(visuals.solidCard, palette.receiptFill, "receiptFill@$skin")
            assertEquals(visuals.textFaint, palette.receiptRule, "receiptRule@$skin")
            assertEquals(states.danger.border, palette.blushFill, "blushFill@$skin")
            assertEquals(states.danger.fg, palette.clipAccent, "clipAccent@$skin")
            assertEquals(states.info.fg, palette.propInfo, "propInfo@$skin")
            assertEquals(states.success.fg, palette.propSuccess, "propSuccess@$skin")
            assertEquals(states.warn.fg, palette.propWarn, "propWarn@$skin")
        }
    }

    @Test
    fun blushNeverCollapsesIntoOutlineOrBody() {
        // 可爱公式的暖色点缀必须独立可辨:腮红与描边/身体同色 = 表情糊掉。
        AppSkin.entries.forEach { skin ->
            val palette = mascotPalette(themeVisualsForSkin(skin), stateTokensForSkin(skin))
            assertEquals(false, palette.blushFill == palette.outline, "blush==outline@$skin")
            assertEquals(false, palette.blushFill == palette.bodyFill, "blush==body@$skin")
        }
    }
}
