package com.ticketbox.ui.components

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R

@Composable
fun DuplicateNotice(
    reason: String?,
    modifier: Modifier = Modifier,
) {
    AppContentCard(modifier = modifier.fillMaxWidth()) {
        Text(
            text = stringResource(R.string.components_duplicate_notice_title),
            color = MaterialTheme.colorScheme.error,
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
