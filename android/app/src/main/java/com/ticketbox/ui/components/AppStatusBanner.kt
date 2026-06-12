package com.ticketbox.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.asString
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.StateTokens
import com.ticketbox.ui.design.StateTone

/**
 * A block status banner — the Android mirror of /web `components/alert.css`
 * `.dt-alert`. Both surfaces draw the same state-pair tokens (bg / fg / border),
 * which are kept in three-surface parity, so this is wiring, not a new visual
 * language.
 *
 * Placed in the page-header slot of [com.ticketbox.ui.screens.settings.SettingsPageFrame]
 * (= the /web flash position), so operation feedback lands where the user is
 * already looking instead of at the bottom of a scrollable page. Renders nothing
 * for a null / blank message.
 *
 * Geometry follows the `.dt-alert` rule (`padding: --space-4 --space-5`,
 * `border: 1px`, `border-radius: --radius-sm`, caption type) expressed through
 * Android design tokens.
 */
@Composable
fun AppStatusBanner(
    message: UiText?,
    tone: MessageTone,
    modifier: Modifier = Modifier,
) {
    val text = message?.asString()?.takeIf { it.isNotBlank() } ?: return
    val palette = LocalStateTokens.current.forTone(tone)
    Text(
        text = text,
        color = palette.fg,
        style = MaterialTheme.typography.bodySmall,
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(AppRadius.small))
            .background(palette.bg)
            .border(1.dp, palette.border, RoundedCornerShape(AppRadius.small))
            .padding(horizontal = AppSpacing.cardGap, vertical = AppSpacing.compactGap),
    )
}

/** Map a VM-held [MessageTone] to its [StateTone] color triple. */
fun StateTokens.forTone(tone: MessageTone): StateTone = when (tone) {
    MessageTone.Success -> success
    MessageTone.Danger -> danger
    MessageTone.Info -> info
    MessageTone.Neutral -> neutral
}
