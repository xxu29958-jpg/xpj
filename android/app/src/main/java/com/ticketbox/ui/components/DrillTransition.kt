package com.ticketbox.ui.components

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedContentScope
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.animation.togetherWith
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.ticketbox.ui.design.AppMotion

/** Stats 卡 → 详情的钻取转场: fade + scale 0.96→1 进入, fade + scale 1→1.04 退出. */
@Composable
fun <S> DrillTransition(
    targetState: S,
    modifier: Modifier = Modifier,
    label: String = "drill",
    content: @Composable AnimatedContentScope.(S) -> Unit,
) {
    AnimatedContent(
        targetState = targetState,
        modifier = modifier,
        transitionSpec = {
            (fadeIn(AppMotion.standardSpec(AppMotion.normalMillis)) +
                scaleIn(initialScale = 0.96f, animationSpec = AppMotion.emphasizedSpec(AppMotion.normalMillis)))
                .togetherWith(
                    fadeOut(AppMotion.exitSpec(AppMotion.fastMillis)) +
                        scaleOut(targetScale = 1.04f, animationSpec = AppMotion.exitSpec(AppMotion.fastMillis))
                )
        },
        label = label,
        content = content,
    )
}
