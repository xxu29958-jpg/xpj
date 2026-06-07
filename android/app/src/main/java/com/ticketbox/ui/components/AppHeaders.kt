package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.sp
import com.ticketbox.R
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTypography
@Composable
fun ScreenHeader(
    title: String,
    subtitle: String? = null,
    modifier: Modifier = Modifier,
    eyebrow: String = stringResource(R.string.components_page_header_eyebrow),
    action: (@Composable RowScope.() -> Unit)? = null,
) {
    Column(modifier = modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        if (eyebrow.isNotBlank()) {
            Text(
                text = eyebrow,
                style = MaterialTheme.typography.titleMedium.copy(
                    fontSize = AppTypography.appLabel.size,
                    lineHeight = 20.sp,
                    letterSpacing = 0.06.sp,
                ),
                color = MaterialTheme.colorScheme.onBackground,
                fontWeight = AppTypography.appLabel.weight,
            )
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
            ) {
                Text(
                    text = title,
                    style = MaterialTheme.typography.titleLarge.copy(
                        fontSize = AppTypography.pageTitle.size,
                        lineHeight = 34.sp,
                        letterSpacing = 0.sp,
                    ),
                    fontWeight = AppTypography.pageTitle.weight,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
                subtitle?.let {
                    Text(
                        text = it,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodyMedium.copy(
                            fontSize = AppTypography.body.size,
                            lineHeight = 22.sp,
                        ),
                    )
                }
            }
            action?.invoke(this)
        }
    }
}

@Composable
fun SectionTitle(
    title: String,
    subtitle: String? = null,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
        Text(
            text = title,
            style = MaterialTheme.typography.titleLarge.copy(
                fontSize = AppTypography.sectionTitle.size,
                lineHeight = 26.sp,
                letterSpacing = 0.sp,
            ),
            color = MaterialTheme.colorScheme.onBackground,
            fontWeight = AppTypography.sectionTitle.weight,
        )
        subtitle?.let {
            Text(
                text = it,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodyMedium.copy(
                    fontSize = AppTypography.body.size,
                    lineHeight = 22.sp,
                ),
            )
        }
    }
}
