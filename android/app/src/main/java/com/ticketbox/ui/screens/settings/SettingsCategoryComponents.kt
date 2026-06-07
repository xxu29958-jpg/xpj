package com.ticketbox.ui.screens.settings

import android.graphics.BitmapFactory
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material.icons.filled.Category
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.CloudDone
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material.icons.filled.FileDownload
import androidx.compose.material.icons.filled.Image
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Palette
import androidx.compose.material.icons.filled.PhotoLibrary
import androidx.compose.material.icons.filled.RestartAlt
import androidx.compose.material.icons.filled.Security
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundCropMode
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.ConnectionDiagnostics
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.DiagnosticStatus
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.domain.model.ServerSettings
import com.ticketbox.ui.appearance.AppearanceDefaults
import com.ticketbox.ui.appearance.BackgroundCatalog
import com.ticketbox.ui.appearance.BuiltInBackground
import com.ticketbox.ui.appearance.BuiltInBackgroundCategory
import com.ticketbox.ui.appearance.background.ImmersiveBackgroundScaffold
import com.ticketbox.ui.appearance.background.SurfaceRole
import com.ticketbox.ui.appearance.background.TicketboxBackgroundLayer
import com.ticketbox.ui.appearance.background.resolveCardContainerAlpha
import com.ticketbox.ui.appearance.background.resolveGlobalScrim
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppPageScrollableColumn
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.SettingsEntryCard
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.components.parseAmountCents
import com.ticketbox.ui.design.AppElevation
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.ThemeVisuals
import com.ticketbox.ui.design.themeVisualsForSkin
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.theme.TicketboxAtmosphereBackground
import com.ticketbox.ui.theme.colorSchemeForSkin
import com.ticketbox.viewmodel.SettingsUiState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

@Composable
internal fun PreviewReceipt(
    title: String,
    amount: String,
    subtitle: String,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            Text(title, style = MaterialTheme.typography.labelLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(subtitle, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
        }
        Text(amount, color = MaterialTheme.colorScheme.onSurface, fontWeight = AppTextHierarchy.heading.weight)
    }
}

@Composable
internal fun rememberLocalImage(path: String): ImageBitmap? {
    var image by remember(path) { mutableStateOf<ImageBitmap?>(null) }
    LaunchedEffect(path) {
        image = withContext(Dispatchers.IO) {
            BitmapFactory.decodeFile(path)?.asImageBitmap()
        }
    }
    return image
}

@Composable
internal fun CategoryRuleCard(
    rule: CategoryRule,
    readOnly: Boolean = false,
    onToggleRule: (CategoryRule) -> Unit,
    onEditRule: () -> Unit,
    onDeleteRule: () -> Unit,
) {
    val currencyDisplay = LocalCurrencyDisplay.current

    AppGlassCard(containerAlpha = 0.98f) {
        Column(modifier = Modifier.padding(AppSpacing.compactGap), verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(rule.keyword, style = MaterialTheme.typography.titleSmall)
                Text(rule.category, color = MaterialTheme.colorScheme.primary)
            }
            Text(
                text = stringResource(
                    R.string.category_rule_card_priority_status,
                    rule.priority,
                    if (rule.enabled) {
                        stringResource(R.string.category_rule_card_status_enabled)
                    } else {
                        stringResource(R.string.category_rule_card_status_disabled)
                    },
                ),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            val conditionText = categoryRuleConditionText(rule, currencyDisplay)
            if (conditionText != null) {
                Text(
                    text = conditionText,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            if (!readOnly) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { onToggleRule(rule) }) {
                        Text(
                            if (rule.enabled) {
                                stringResource(R.string.category_rule_card_action_disable)
                            } else {
                                stringResource(R.string.category_rule_card_action_enable)
                            },
                        )
                    }
                    OutlinedButton(onClick = onEditRule) {
                        Text(stringResource(R.string.category_rule_card_action_edit))
                    }
                    OutlinedButton(onClick = onDeleteRule) {
                        Text(stringResource(R.string.category_rule_card_action_delete))
                    }
                }
            }
        }
    }
}

@Composable
private fun categoryRuleConditionText(
    rule: CategoryRule,
    currencyDisplay: CurrencyDisplay,
): String? {
    if (!rule.hasConditions) return null
    val parts = buildList {
        rule.amountMinCents?.let {
            add(stringResource(R.string.category_rule_condition_amount_min, formatDisplayAmount(it, currencyDisplay)))
        }
        rule.amountMaxCents?.let {
            add(stringResource(R.string.category_rule_condition_amount_max, formatDisplayAmount(it, currencyDisplay)))
        }
        rule.sourceContains?.takeIf { it.isNotBlank() }?.let {
            add(stringResource(R.string.category_rule_condition_source_contains, it))
        }
        rule.tagContains?.takeIf { it.isNotBlank() }?.let {
            add(stringResource(R.string.category_rule_condition_tag, it))
        }
    }
    return parts.joinToString(" · ")
}

@Composable
internal fun categoryRuleSummary(rules: List<CategoryRule>): String {
    val enabled = rules.count { it.enabled }
    return if (rules.isEmpty()) {
        stringResource(R.string.category_rules_summary_empty)
    } else {
        stringResource(R.string.category_rules_summary_count, enabled, rules.size)
    }
}
