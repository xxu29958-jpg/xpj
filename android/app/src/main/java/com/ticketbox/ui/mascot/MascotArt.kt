package com.ticketbox.ui.mascot

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.core.LinearEasing
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.design.LocalAppSkin
import com.ticketbox.ui.design.LocalReduceMotion

/**
 * 状态 × 渲染主题到真实图片资产的唯一映射。可见态只有两族:空态 Dozing(平静闭眼)
 * 与里程碑 Celebrating(弯眼+彩带);其余状态(含事件发射前的 Neutral 首帧)一律落
 * Dozing 平静脸,不留「无资产可显」的第三分支。映射有 [MascotArtTest] 钉死。
 */
internal fun mascotArtRes(state: MascotState, skin: AppSkin): Int = when (state) {
    MascotState.Celebrating -> when (skin) {
        AppSkin.Paper -> R.drawable.mascot_celebrating_paper
        AppSkin.Midnight -> R.drawable.mascot_celebrating_midnight
    }
    else -> when (skin) {
        AppSkin.Paper -> R.drawable.mascot_dozing_paper
        AppSkin.Midnight -> R.drawable.mascot_dozing_midnight
    }
}

/**
 * 夹夹的正式渲染宿主:W2-A 起由原生 Compose 线稿切换为品牌原生图片资产
 * (剪影与 Web brand mark 同源的四张品牌 PNG),paper/midnight 按 [LocalAppSkin]
 * 自动换源。动效只做整体 transform(呼吸级缓慢浮动),不做形变、不烘焙多帧;
 * 状态表达(闭眼/弯眼/彩带)全部在资产里。事件线仍是 [MascotController] →
 * [MascotStateMachine],这里只消费 state,不回写任何业务状态。
 *
 * 「减少动态效果」([LocalReduceMotion],owner=BackgroundSettings)开启时不启动
 * 无限动画,静态落位。2400ms 是沿用 V4 呼吸期的 mascot 环境节拍——AppMotion 四档
 * 是 UI 过渡时长,不适用于这类不抢焦点的环境循环,故为 mascot 专属常量。
 */
@Composable
fun MascotArt(
    state: MascotState,
    modifier: Modifier = Modifier,
    size: Dp = 96.dp,
) {
    val painter = painterResource(mascotArtRes(state, LocalAppSkin.current))
    if (LocalReduceMotion.current) {
        Image(
            painter = painter,
            contentDescription = null,
            modifier = modifier.size(size),
        )
        return
    }
    val transition = rememberInfiniteTransition(label = "mascot-art-motion")
    val breath by transition.animateFloat(
        initialValue = -1f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(MASCOT_ART_BREATH_MS, easing = LinearEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "breath",
    )
    val bobPx = with(LocalDensity.current) { MASCOT_ART_BOB.toPx() }
    Image(
        painter = painter,
        contentDescription = null,
        modifier = modifier
            .size(size)
            .graphicsLayer { translationY = breath * bobPx },
    )
}

private const val MASCOT_ART_BREATH_MS = 2400
private val MASCOT_ART_BOB = 2.dp
