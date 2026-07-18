package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AttachMoney
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.AppSpacing

@Composable
internal fun CurrencySection(
    currentCurrency: CurrencyCode,
) {
    SettingsSection(title = stringResource(R.string.currency_section_title), icon = Icons.Filled.AttachMoney) {
        SettingsOpenPanel(
            verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            Text(
                text = stringResource(R.string.currency_section_intro),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
            Text(
                text = stringResource(R.string.currency_section_rate_home, currentCurrency.storageKey),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            ) {
                Text(
                    text = currentCurrency.symbol,
                    color = MaterialTheme.colorScheme.primary,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = AppTextHierarchy.body.weight,
                )
                Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
                    Text(
                        text = currentCurrency.displayName,
                        style = MaterialTheme.typography.bodyMedium,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text(
                        text = currentCurrency.storageKey,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.labelSmall,
                    )
                }
            }
        }
    }
}
