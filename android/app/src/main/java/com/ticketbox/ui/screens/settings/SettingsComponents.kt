package com.ticketbox.ui.screens.settings

import android.graphics.BitmapFactory
import androidx.annotation.DrawableRes
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
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.res.vectorResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.ConnectionDiagnostics
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
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppAdaptiveEditAmountRow
import com.ticketbox.ui.components.AppPageChrome
import com.ticketbox.ui.components.AppPageScrollableColumn
import com.ticketbox.ui.components.AppScrollablePageChrome
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryPageHeader
import com.ticketbox.ui.components.AppSecondaryPageSlots
import com.ticketbox.ui.components.AppSecondaryScrollableColumn
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.components.formatAmount
import com.ticketbox.ui.components.formatAmountInput
import com.ticketbox.ui.components.parseAmountCents
import com.ticketbox.ui.components.SettingsEntryIcon
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppAdaptiveContentWidth
import com.ticketbox.ui.design.asTextStyle
import com.ticketbox.ui.design.AppElevation
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.SettingsColors
import com.ticketbox.ui.design.ThemeVisuals
import com.ticketbox.ui.design.themeVisualsForSkin
import com.ticketbox.ui.theme.TicketboxAtmosphereBackground
import com.ticketbox.ui.theme.colorSchemeForSkin
import com.ticketbox.viewmodel.SettingsUiState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

data class SettingsEntryRowOptions(
    val expanded: Boolean? = null,
    val modifier: Modifier = Modifier,
    val amount: String? = null,
    val supportingContent: (@Composable () -> Unit)? = null,
)

@Composable
fun SettingsEntryRow(
    title: String,
    subtitle: String,
    @DrawableRes icon: Int,
    onClick: (() -> Unit)?,
    options: SettingsEntryRowOptions = SettingsEntryRowOptions(),
) {
    val expansionLabel = stringResource(
        if (options.expanded == true) R.string.settings_account_toggle_collapse else R.string.settings_account_toggle_expand,
    )
    Column(
        modifier = options.modifier
            .fillMaxWidth()
            .semantics { options.expanded?.let { stateDescription = expansionLabel } }
            .then(if (onClick != null) Modifier.clickable(role = Role.Button, onClick = onClick) else Modifier),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = 68.dp)
                .padding(vertical = AppSpacing.compactGap),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            SettingsEntryIcon(
                icon = ImageVector.vectorResource(icon),
                modifier = Modifier.size(40.dp),
                background = settingsEntryBackground(icon),
                shape = RoundedCornerShape(AppRadius.medium),
            )
            val labels: @Composable () -> Unit = {
                Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
                    Text(
                        text = title,
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = AppTextHierarchy.heading.weight,
                    )
                    if (subtitle.isNotBlank()) Text(
                        text = subtitle,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall,
                    )
                    options.supportingContent?.invoke()
                }
            }
            if (options.amount == null) {
                Box(modifier = Modifier.weight(1f)) { labels() }
            } else {
                AppAdaptiveEditAmountRow(amount = options.amount, modifier = Modifier.weight(1f), content = labels)
            }
            if (onClick != null) Icon(
                imageVector = ImageVector.vectorResource(R.drawable.ic_lucide_chevron_right),
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.size(AppSpacing.cardPadding).rotate(if (options.expanded == true) 90f else 0f),
            )
        }
        HorizontalDivider(
            color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium),
        )
    }
}

@Composable
private fun settingsEntryBackground(@DrawableRes icon: Int): Color {
    val tint = when (icon) {
        R.drawable.ic_lucide_users, R.drawable.ic_lucide_info, R.drawable.ic_lucide_image,
        R.drawable.ic_lucide_git_branch, R.drawable.ic_lucide_shopping_bag -> SettingsColors.householdEntry
        R.drawable.ic_lucide_palette, R.drawable.ic_lucide_images, R.drawable.ic_lucide_wifi,
        R.drawable.ic_lucide_calendar_check -> SettingsColors.appearanceEntry
        R.drawable.ic_lucide_refresh_cw, R.drawable.ic_lucide_user_round_x -> SettingsColors.connectionEntry
        else -> SettingsColors.generalEntry
    }
    return tint
}

@Composable
internal fun SettingsPageFrame(
    title: String,
    subtitle: String,
    onBack: (() -> Unit)?,
    // Page-header status slot (= /web flash position): rendered between the
    // header and the content so operation feedback appears where the user is
    // already looking, not at the bottom of the scroll. Default null leaves the
    // callers that pass no status untouched.
    status: (@Composable () -> Unit)? = null,
    content: @Composable () -> Unit,
) {
    BackHandler(enabled = onBack != null) { onBack?.invoke() }
    AppPageScrollableColumn(
        chrome = AppScrollablePageChrome(
            page = AppPageChrome(role = AppPageRole.Settings, hasBottomBar = false),
            contentWidth = AppAdaptiveContentWidth.Secondary,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.sectionGap),
        ),
    ) {
        SettingsPageHeading(title, subtitle, onBack)
        status?.invoke()
        content()
    }
}

@Composable
internal fun SettingsPageHeading(title: String, subtitle: String, onBack: (() -> Unit)?,
    backLabel: String = stringResource(R.string.settings_root_page_title)) {
    AppSecondaryPageHeader(
        title = title,
        subtitle = subtitle,
        backText = if (backLabel == stringResource(R.string.settings_root_page_title))
            stringResource(R.string.settings_page_back_to_settings) else backLabel,
        onBack = onBack,
    )
}

/** A compact entry keeps the overview readable; original controls live in its explicit details. */
@Composable
internal fun SettingsDetailRow(
    title: String,
    subtitle: String,
    @DrawableRes icon: Int,
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit,
) {
    var expanded by rememberSaveable { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        SettingsEntryRow(
            title,
            subtitle,
            icon,
            onClick = { expanded = !expanded },
            options = SettingsEntryRowOptions(expanded = expanded, modifier = modifier),
        )
        if (expanded) Column(modifier = Modifier.padding(start = AppSpacing.compactGap), content = content)
    }
}

@Composable
internal fun ManagementPageFrame(
    header: ManagementPageHeader,
    onBack: (() -> Unit)?,
    status: (@Composable () -> Unit)? = null,
    content: @Composable () -> Unit,
) {
    AppSecondaryScrollableColumn(
        chrome = AppSecondaryPageChrome(
            role = header.chrome.role,
            title = header.title,
            subtitle = header.subtitle,
            backText = header.chrome.backText ?: stringResource(R.string.settings_page_back_to_settings),
            onBack = onBack,
            hasBottomBar = false,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ),
        slots = AppSecondaryPageSlots(status = status),
    ) {
        content()
    }
}

data class ManagementPageHeader(
    val title: String,
    val subtitle: String,
    val chrome: ManagementPageChrome = ManagementPageChrome(),
)

data class ManagementPageChrome(
    val role: AppPageRole = AppPageRole.Settings,
    val backText: String? = null,
)

@Composable
internal fun BackgroundActionButton(
    text: String,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    leadingIcon: ImageVector? = null,
    onClick: () -> Unit,
) {
    AppSecondaryButton(
        text = text,
        modifier = modifier,
        enabled = enabled,
        leadingIcon = leadingIcon,
        onClick = onClick,
    )
}

@Composable
internal fun SettingsOpenPanel(
    modifier: Modifier = Modifier,
    verticalArrangement: Arrangement.Vertical = Arrangement.spacedBy(AppSpacing.compactGap),
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(vertical = AppSpacing.miniGap),
        verticalArrangement = verticalArrangement,
        content = content,
    )
}

@Composable
internal fun SettingsInlineEmpty(
    title: String,
    body: String,
    modifier: Modifier = Modifier,
) {
    SettingsOpenPanel(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        Text(
            text = title,
            style = MaterialTheme.typography.titleSmall,
        )
        Text(
            text = body,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}

@Composable
internal fun SettingsDialogTextInput(
    state: SettingsTextInputState,
    onValueChange: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    AppTextInput(
        state = AppTextInputState(
            label = state.label,
            value = state.value,
            placeholder = state.placeholder,
            enabled = state.enabled,
            singleLine = state.singleLine,
            minLines = state.minLines,
            maxLines = state.maxLines,
            keyboardOptions = state.keyboardOptions,
            readOnly = state.readOnly,
        ),
        actions = AppTextInputActions(onValueChange = onValueChange),
        modifier = modifier.fillMaxWidth(),
    )
}

internal data class SettingsTextInputState(
    val label: String,
    val value: String,
    val placeholder: String = "",
    val enabled: Boolean = true,
    val singleLine: Boolean = true,
    val minLines: Int = 1,
    val maxLines: Int = 3,
    val keyboardOptions: KeyboardOptions = KeyboardOptions.Default,
    val readOnly: Boolean = false,
)
