package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens

@Composable
fun DuplicateNotice(
    reason: String?,
    modifier: Modifier = Modifier,
) {
    val tone = LocalStateTokens.current.warn
    Column(
        modifier = modifier
            .fillMaxWidth()
            .drawBehind {
                val stroke = AppSpacing.tinyGap.toPx()
                drawLine(
                    color = tone.fg,
                    start = Offset(0f, 0f),
                    end = Offset(0f, size.height),
                    strokeWidth = stroke,
                )
            }
            .padding(start = AppSpacing.contentGap, top = AppSpacing.tinyGap, bottom = AppSpacing.tinyGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
    ) {
        Text(
            text = stringResource(R.string.components_duplicate_notice_title),
            color = tone.fg,
            style = MaterialTheme.typography.labelLarge,
        )
        Text(
            text = duplicateNoticeBody(reason),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}

@Composable
fun duplicateNoticeBody(reason: String?): String {
    val normalized = reason.orEmpty().trim()
    return when {
        normalized.hasAnyReasonToken(
            "image hash",
            "perceptual hash",
            "hash",
        ) -> stringResource(R.string.components_duplicate_notice_image_hash)
        normalized.hasAnyReasonToken(
            "amount",
            "merchant",
            "time",
            "field",
        ) -> stringResource(R.string.components_duplicate_notice_field_match)
        else -> stringResource(R.string.components_duplicate_notice_generic)
    }
}

private fun String.hasAnyReasonToken(vararg tokens: String): Boolean =
    tokens.any { contains(it, ignoreCase = true) }
