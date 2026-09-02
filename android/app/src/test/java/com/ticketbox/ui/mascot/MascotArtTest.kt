package com.ticketbox.ui.mascot

import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * 钉死 mascot 状态 × 渲染主题到真实图片资产的映射:空态 Dozing 与里程碑
 * Celebrating 各有 paper/midnight 双源;其余状态(含事件未发射前的 Neutral 首帧)
 * 一律落到 Dozing 的平静脸,不允许出现「无资产可显」的第三分支。
 * 换图/串主题(比如 midnight 显示了 paper 资产)直接翻红。
 */
class MascotArtTest {

    @Test
    fun dozingResolvesToDozingAssetPerSkin() {
        assertEquals(R.drawable.mascot_dozing_paper, mascotArtRes(MascotState.Dozing, AppSkin.Paper))
        assertEquals(R.drawable.mascot_dozing_midnight, mascotArtRes(MascotState.Dozing, AppSkin.Midnight))
    }

    @Test
    fun celebratingResolvesToCelebratingAssetPerSkin() {
        assertEquals(R.drawable.mascot_celebrating_paper, mascotArtRes(MascotState.Celebrating, AppSkin.Paper))
        assertEquals(R.drawable.mascot_celebrating_midnight, mascotArtRes(MascotState.Celebrating, AppSkin.Midnight))
    }

    @Test
    fun nonCelebratingStatesFallBackToCalmDozingAsset() {
        listOf(MascotState.Neutral, MascotState.Greeting, MascotState.Dismissive).forEach { state ->
            AppSkin.entries.forEach { skin ->
                val expected = if (skin == AppSkin.Paper) {
                    R.drawable.mascot_dozing_paper
                } else {
                    R.drawable.mascot_dozing_midnight
                }
                assertEquals(expected, mascotArtRes(state, skin), "$state@$skin")
            }
        }
    }
}
