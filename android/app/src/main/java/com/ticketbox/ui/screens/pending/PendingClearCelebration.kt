package com.ticketbox.ui.screens.pending

import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.components.ClearCelebration

/**
 * 待确认清零庆祝动画。
 *
 * 触发：从「有待确认」过渡到「全部清零」的瞬间。动画体已抽到通用 [ClearCelebration]
 * （ADR-0049 §5.3 / slice 8e-4）以与成员债两清共用；本函数仅做文案转发，视觉零变化。
 */
@Composable
internal fun PendingClearCelebration(visible: Boolean) {
    ClearCelebration(
        visible = visible,
        title = stringResource(R.string.pending_celebration_title),
        body = stringResource(R.string.pending_celebration_body),
        checkDescription = stringResource(R.string.pending_celebration_check_desc),
    )
}
