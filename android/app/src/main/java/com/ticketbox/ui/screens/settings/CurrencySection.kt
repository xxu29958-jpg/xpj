package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AttachMoney
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.FxContract
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalThemeVisuals

@Composable
internal fun CurrencySection(
    currentCurrency: CurrencyCode,
    onCurrencyChange: (CurrencyCode) -> Unit,
) {
    val rateLine = if (currentCurrency == FxContract.HomeCurrency) {
        stringResource(R.string.currency_section_rate_home, FxContract.HomeCurrency.storageKey)
    } else {
        stringResource(
            R.string.currency_section_rate_foreign,
            currentCurrency.storageKey,
            FxContract.HomeCurrency.storageKey,
        )
    }
    SettingsSection(title = stringResource(R.string.currency_section_title), icon = Icons.Filled.AttachMoney) {
        AppGlassCard(containerAlpha = 0.96f) {
            Column(
                modifier = Modifier.padding(AppSpacing.cardPaddingTight),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            ) {
                Text(
                    text = stringResource(R.string.currency_section_intro),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
                Text(
                    text = rateLine,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
                CurrencyCode.entries.chunked(2).forEach { rowCodes ->
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
                    ) {
                        rowCodes.forEach { code ->
                            CurrencyOptionCard(
                                modifier = Modifier.weight(1f),
                                currency = code,
                                selected = code == currentCurrency,
                                onClick = { onCurrencyChange(code) },
                            )
                        }
                        if (rowCodes.size == 1) {
                            Spacer(modifier = Modifier.weight(1f))
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun CurrencyOptionCard(
    modifier: Modifier = Modifier,
    currency: CurrencyCode,
    selected: Boolean,
    onClick: () -> Unit,
) {
    val visuals = LocalThemeVisuals.current
    val container = if (selected) {
        visuals.glassTint.copy(alpha = 0.78f)
    } else {
        MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.32f)
    }
    val border = if (selected) visuals.primary else Color.Transparent
    val shape = RoundedCornerShape(AppRadius.small)

    Box(
        modifier = modifier
            .height(68.dp)
            .clip(shape)
            .background(container)
            .border(1.dp, border, shape)
            .clickable(onClick = onClick)
            .padding(horizontal = AppSpacing.contentGap, vertical = AppSpacing.smallGap),
    ) {
        Row(
            modifier = Modifier.fillMaxSize(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            // 币种符号 badge
            Box(
                modifier = Modifier
                    .size(36.dp)
                    .clip(RoundedCornerShape(AppRadius.small))
                    .background(visuals.chipSelected.copy(alpha = 0.6f)),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = currency.symbol,
                    color = visuals.primary,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = AppTextHierarchy.body.weight,
                )
            }
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(2.dp),
            ) {
                Text(
                    text = currency.displayName,
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    text = currency.storageKey,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelSmall,
                )
            }
            if (selected) {
                Icon(
                    imageVector = Icons.Filled.Check,
                    contentDescription = stringResource(R.string.currency_section_option_selected_content_description),
                    tint = visuals.primary,
                    modifier = Modifier.size(18.dp),
                )
            }
        }
    }
}
