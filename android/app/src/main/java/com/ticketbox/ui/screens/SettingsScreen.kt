package com.ticketbox.ui.screens

import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.integerResource
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.ui.appearance.background.BackgroundImageStore
import com.ticketbox.ui.screens.settings.AboutScreen
import com.ticketbox.ui.screens.settings.AppearanceScreen
import com.ticketbox.ui.screens.settings.BackgroundCropScreen
import com.ticketbox.ui.screens.settings.BackgroundGalleryScreen
import com.ticketbox.ui.screens.settings.BackgroundPreviewScreen
import com.ticketbox.ui.screens.settings.CategoryRulesScreen
import com.ticketbox.ui.screens.settings.DataExportScreen
import com.ticketbox.ui.screens.settings.LedgerSwitcherScreen
import com.ticketbox.ui.screens.settings.JoinFamilyLedgerScreen
import com.ticketbox.ui.screens.settings.SecurityPrivacyScreen
import com.ticketbox.ui.screens.settings.ServerSettingsScreen
import com.ticketbox.ui.screens.settings.SettingsRootScreen
import com.ticketbox.ui.screens.settings.SettingsRoute
import com.ticketbox.viewmodel.SettingsUiState

@Composable
fun SettingsScreen(
    state: SettingsUiState,
    currentSkin: AppSkin,
    onTestConnection: () -> Unit,
    onRunDiagnostics: () -> Unit,
    onRefreshServerSettings: () -> Unit,
    onSync: () -> Unit,
    onClearCache: () -> Unit,
    onSaveMonthlyBudget: (Long?) -> Unit,
    onCreateRule: (String, String, Int) -> Unit,
    onUpdateRule: (CategoryRule, String, String, Int) -> Unit,
    onToggleRule: (CategoryRule) -> Unit,
    onDeleteRule: (CategoryRule) -> Unit,
    onSkinChange: (AppSkin) -> Unit,
    onApplyBackgroundSettings: (BackgroundSettings) -> Unit,
    onClearBackgroundImage: () -> Unit,
    onBackgroundImageError: (String) -> Unit = {},
    onImmersionModeChange: (ImmersionMode) -> Unit,
    onParallaxChange: (Boolean) -> Unit,
    onReduceMotionChange: (Boolean) -> Unit,
    onBindingCleared: () -> Unit,
    showAdvancedTools: Boolean = false,
    ledgerRepository: LedgerRepository? = null,
    activeLedgerId: String? = null,
    onLedgerSwitched: () -> Unit = {},
) {
    var route by remember { mutableStateOf<SettingsRoute>(SettingsRoute.Root) }
    val context = LocalContext.current
    val backgroundImageStore = remember(context) { BackgroundImageStore(context) }
    val appVersionName = stringResource(R.string.app_version_name)
    val appVersionCode = integerResource(R.integer.app_version_code)

    val backgroundPickerLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.PickVisualMedia(),
    ) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        runCatching {
            backgroundImageStore.copyPickedImageToPrivateStorage(uri)
        }
            .onSuccess { path -> route = SettingsRoute.BackgroundCrop(path) }
            .onFailure { onBackgroundImageError("背景没有保存成功，请换一张图片再试。") }
    }

    fun launchImagePicker() {
        backgroundPickerLauncher.launch(
            PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly),
        )
    }

    fun previewThemeDefault() {
        onApplyBackgroundSettings(state.backgroundSettings.withoutBackground())
    }

    BackHandler(enabled = route != SettingsRoute.Root) {
        route = when (route) {
            SettingsRoute.BackgroundGallery,
            is SettingsRoute.BackgroundCrop,
            is SettingsRoute.BackgroundPreview
            -> SettingsRoute.Appearance
            else -> SettingsRoute.Root
        }
    }

    when (val currentRoute = route) {
        SettingsRoute.Root -> SettingsRootScreen(
            state = state,
            showAdvancedTools = showAdvancedTools,
            onOpenServer = { route = SettingsRoute.Server },
            onOpenAppearance = { route = SettingsRoute.Appearance },
            onOpenCategoryRules = { route = SettingsRoute.CategoryRules },
            onOpenDataExport = { route = SettingsRoute.DataExport },
            onOpenSecurity = { route = SettingsRoute.SecurityPrivacy },
            onOpenLedgers = { route = SettingsRoute.Ledgers },
            onOpenJoinFamilyLedger = { route = SettingsRoute.JoinFamilyLedger },
            onOpenAbout = { route = SettingsRoute.About },
        )

        SettingsRoute.Server -> ServerSettingsScreen(
            state = state,
            showAdvancedTools = showAdvancedTools,
            onBack = { route = SettingsRoute.Root },
            onTestConnection = onTestConnection,
            onRunDiagnostics = onRunDiagnostics,
            onRefreshServerSettings = onRefreshServerSettings,
            onSync = onSync,
        )

        SettingsRoute.Appearance -> AppearanceScreen(
            state = state,
            currentSkin = currentSkin,
            onBack = { route = SettingsRoute.Root },
            onSkinChange = onSkinChange,
            onOpenGallery = { route = SettingsRoute.BackgroundGallery },
            onPickCustomImage = ::launchImagePicker,
            onPreviewThemeDefault = ::previewThemeDefault,
            onClearBackgroundImage = {
                backgroundImageStore.deleteCustomBackground(state.backgroundSettings.customImagePath)
                onClearBackgroundImage()
            },
            onImmersionModeChange = onImmersionModeChange,
            onParallaxChange = onParallaxChange,
            onReduceMotionChange = onReduceMotionChange,
        )

        SettingsRoute.BackgroundGallery -> BackgroundGalleryScreen(
            currentSettings = state.backgroundSettings,
            onBack = { route = SettingsRoute.Appearance },
            onPickCustomImage = ::launchImagePicker,
            onPreviewThemeDefault = ::previewThemeDefault,
            onPreviewBuiltIn = { background ->
                route = SettingsRoute.BackgroundPreview(
                    settings = state.backgroundSettings.withBuiltInBackground(background.id),
                    title = background.name,
                )
            },
        )

        is SettingsRoute.BackgroundCrop -> BackgroundCropScreen(
            sourcePath = currentRoute.sourcePath,
            onBack = { route = SettingsRoute.Appearance },
            onComplete = { cropMode ->
                runCatching {
                    backgroundImageStore.cropPickedImageToPrivateStorage(
                        sourcePath = currentRoute.sourcePath,
                        cropMode = cropMode,
                    )
                }
                    .onSuccess { croppedPath ->
                        route = SettingsRoute.BackgroundPreview(
                            settings = state.backgroundSettings
                                .withCustomImage(croppedPath)
                                .copy(cropMode = cropMode),
                            title = "自定义背景",
                        )
                    }
                    .onFailure { onBackgroundImageError("背景裁剪没有完成，请换一张图片再试。") }
            },
        )

        is SettingsRoute.BackgroundPreview -> BackgroundPreviewScreen(
            initialSettings = currentRoute.settings,
            currentSkin = currentSkin,
            title = currentRoute.title,
            onBack = { route = SettingsRoute.Appearance },
            onApply = { settings ->
                onApplyBackgroundSettings(settings)
                route = SettingsRoute.Appearance
            },
        )

        SettingsRoute.CategoryRules -> CategoryRulesScreen(
            rules = state.categoryRules,
            busy = state.busy,
            onBack = { route = SettingsRoute.Root },
            onCreateRule = onCreateRule,
            onUpdateRule = onUpdateRule,
            onToggleRule = onToggleRule,
            onDeleteRule = onDeleteRule,
        )

        SettingsRoute.DataExport -> DataExportScreen(
            state = state,
            onBack = { route = SettingsRoute.Root },
            onSync = onSync,
            onClearCache = onClearCache,
            onSaveMonthlyBudget = onSaveMonthlyBudget,
        )

        SettingsRoute.SecurityPrivacy -> SecurityPrivacyScreen(
            onBack = { route = SettingsRoute.Root },
            onClearCache = onClearCache,
            onBindingCleared = onBindingCleared,
        )

        SettingsRoute.Ledgers -> {
            val repo = ledgerRepository
            if (repo != null) {
                LedgerSwitcherScreen(
                    repository = repo,
                    activeLedgerId = activeLedgerId,
                    onBack = { route = SettingsRoute.Root },
                    onSwitched = onLedgerSwitched,
                )
            } else {
                // Defensive: if the screen is wired without a repository
                // (e.g. previews) just fall back to the root.
                route = SettingsRoute.Root
            }
        }

        SettingsRoute.JoinFamilyLedger -> {
            val repo = ledgerRepository
            if (repo != null) {
                JoinFamilyLedgerScreen(
                    repository = repo,
                    onBack = { route = SettingsRoute.Root },
                    onAccepted = {
                        // After a successful accept, jump to the ledger
                        // picker so the user can see the joined ledger as
                        // active and other binding-aware screens refresh.
                        onLedgerSwitched()
                        route = SettingsRoute.Ledgers
                    },
                )
            } else {
                route = SettingsRoute.Root
            }
        }

        SettingsRoute.About -> AboutScreen(
            appVersionName = appVersionName,
            appVersionCode = appVersionCode,
            onBack = { route = SettingsRoute.Root },
        )
    }
}
